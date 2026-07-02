# 005 結合試験と CI (M5)

日付: 2026-07-02

## 重要: この環境では未実行・未検証

**開発環境(このマシン)には Docker デーモンが入っていない**
(`docker-compose` バイナリはあるが `docker` 本体が無い)ため、以下に書く
docker-compose 構成・シナリオスクリプトは一度も実行できていない。
設計書とベストプラクティスに基づいて作成したが、初回の GitHub Actions 実行
(または Docker が使えるローカル環境での `make integration`)で以下を
重点的に確認すること:

- レプリケーションセットアップの SQL(`CHANGE MASTER TO` / `START SLAVE`
  構文。MariaDB 10.11/11.4 は `START REPLICA` 系の新構文もサポートするが
  互換性重視で旧構文を使用)が両バージョンで通るか
- `mariadb-backup` パッケージが `mariabackup` という実行ファイル名を
  提供するか(提供しない場合に備え entrypoint でシンボリックリンクを
  張る保険を入れているが未検証)
- `docker compose exec -d` でバックグラウンド起動した `mariadbd` が
  restore-target 内で正しく listen するか、`mariadb-admin ping` の
  ヘルスチェックループが機能するか
- store コンテナのヘルスチェック(`nc -z 127.0.0.1 22`)のタイミング
- シナリオ 02 で `docker compose stop store` 後の `mbkeeper run` が
  本当に exit code 8 を返すか(ユニットテストでは local destination の
  みでこのパスを検証済みだが、ssh destination 込みの実地検証はこれが初)

## 実装したもの

- `tests/integration/docker-compose.yml`: primary(mariadb 公式イメージ)、
  replica(mariabackup-keeper 本体を pip install した独自イメージ)、
  store(sshd+rsync の保管先ノード役)、restore-target(`profiles: [restore]`
  で明示指定時のみ起動する使い捨てリストア検証用ノード)。
- SSH 鍵交換: リポジトリに秘密鍵を絶対にコミットしない方針とするため、
  replica コンテナの entrypoint が起動時に ed25519 鍵ペアをその場で生成し、
  named volume `ssh_keys` に置く。store コンテナの entrypoint は公開鍵が
  volume に現れるまで待ってから `authorized_keys` に追加する。
- `tests/integration/run.sh`: 唯一のエントリポイント。
  `COMPOSE_PROJECT_NAME=mbkeeper-it-$$` でプロジェクト名をユニーク化、
  `trap cleanup EXIT` で必ず `docker compose down -v`(失敗時はテアダウン
  前に `docker compose logs` を `/tmp/mbkeeper-it-logs/compose.log` へ保存し、
  CI 側がそれを artifact としてアップロードできるようにした)。
  primary/replica のヘルスチェック待ち→レプリケーション設定
  (CHANGE MASTER TO ... START SLAVE)→レプリケーション確立待ち→
  `scenarios/*.sh` を順次実行、という流れ。
- シナリオ 3 本:
  1. `01_full_backup_restore.sh`: primary にデータ投入→レプリカで
     `mbkeeper run`→取得した世代を `restore-target`(使い捨て、
     entrypoint を sleep infinity で上書きして自動初期化を止めている)へ
     `mariadb-backup --copy-back`→起動→primary と restore-target の
     `CHECKSUM TABLE` が一致することを検証。
  2. `02_cross_backup.sh`: local + ssh(store)の2保管先へ配置されること、
     両者のファイル一覧・サイズが一致すること(`find -printf` の出力比較)、
     store を停止した状態での再実行が exit code 8(PARTIAL、best-effort)
     を返し local には新世代が入ることを検証。
  3. `03_purge.sh`: keep=2 の設定で 4 回実行し、最終的に世代が2つだけ
     (かつ最新2つ)残ることを検証。
- `.github/workflows/ci.yml`: `unit` ジョブ(Python 3.9/3.11/3.13 ×
  ruff check/format + pytest tests/unit)と `integration` ジョブ
  (MariaDB 10.11/11.4 × `tests/integration/run.sh` をそのまま呼ぶだけ。
  ローカルと CI でテストロジックを一切分岐させない)。失敗時は
  run.sh が保存したログを artifact としてアップロード。

## 副次的な修正

- `pyproject.toml` の dev 依存 `ruff>=0.4` を `ruff==0.4.10` に固定した。
  理由: pre-commit の `.pre-commit-config.yaml` は `rev: v0.4.10` で
  ruff を固定しているのに、`pip install -e ".[dev]"` 側は unpinned だった
  ため、ローカル venv とプリコミットフックとで ruff のバージョンが
  ずれて import 整形結果が食い違う事象が発生した。CI (`pip install -e
  ".[dev]"`)でも同じズレが起きうるため、バージョンを一致させて解消した。

## 次にやること(M6、および M5 の実地検証)

- README.md(商標免責・責任分界)、docs/ 4 ファイル
- Docker が使える環境で `make integration` を実行し、上記の未検証項目を
  一つずつ確認・修正する
