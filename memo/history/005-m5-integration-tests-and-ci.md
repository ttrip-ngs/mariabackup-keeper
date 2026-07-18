# 005 結合試験と CI (M5)

日付: 2026-07-02

## 重要: 作成当初は未検証(→ 2026-07-18 に Apple Container で検証済み)

**注記**: 下記は作成当初(2026-07-02)の状況。その後 Apple Container で
3シナリオを実行し成功した。最新の検証結果は「追記(2026-07-18)」節を参照。

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

## 追記(2026-07-18): Apple Container で検証済み

開発機(Apple Silicon Mac / macOS 26)には Docker デーモンが無いままだが、
Apple の `container` CLI(1.1.0)が使えるようになったため、Docker Compose
版とは別に `tests/integration/run-container.sh` を用意して結合試験を実行した。
CI の正規ハーネス(`run.sh` + Docker Compose)は変更せず温存し、これは
ローカル専用の二次経路という位置づけ。

MariaDB 11.4 で 3 シナリオ全て成功(exit 0)。上記「未検証項目」の実地確認結果:

- レプリケーション設定(`CHANGE MASTER TO ... START SLAVE` 旧構文)は 11.4 で
  問題なく確立(`Slave_IO_Running: Yes` / `Slave_SQL_Running: Yes`)
- `mariadb-backup` パッケージが `mariabackup` 実行ファイルを提供することを確認
- シナリオ1: primary/restored 双方の `CHECKSUM TABLE` が `409448193` で一致。
  物理リストアの実効性を実証
- シナリオ2: 2保管先(local+ssh)で世代一致。store 停止時の再実行が
  期待どおり **exit code 8**(PARTIAL)を返し、local には新世代が入った。
  ssh destination 込みの best-effort 継続を実地で初検証
- シナリオ3: keep=2 で 4 回実行し、生存世代がちょうど 2 つ(最新2つ)に収束

run-container.sh 作成時に必要だった調整(このコミットに含む):
- `debian:bookworm-slim` は `backup`(uid/gid 34)システムアカウントを持つため
  保管先ユーザーは `mbkbackup` に改名
- 読み取り専用マウントのソースツリーからは pip が egg-info を書けず失敗するため、
  書き込み可能パスへコピーしてからインストール
- sshd はデーモンを別途 `container exec -d` で起動(compose の常駐前提が無い)

### GitHub Actions 初回実行(2026-07-18、PR #1)で判明・修正した3件

Public リポジトリ(ttrip-ngs/mariabackup-keeper)を作成し PR #1 で CI を
初めて回したところ、Docker Compose 版(`run.sh`)で3件の不具合が順に露見した。
いずれも Apple Container で実環境を再現して原因を確定し、修正後に CI 全緑
(unit 3.9/3.11/3.13 + integration MariaDB 10.11/11.4)を確認した。

1. レプリケーション確立待ちが `mariadb -N ... "SHOW SLAVE STATUS\G"` を
   使っていた。`-N`(--skip-column-names)は `\G` 縦形式では列名ラベルまで
   抑制するため出力から `Slave_IO_Running:` の文字列が消え、
   `grep 'Slave_IO_Running: Yes'` が永久に空振り。レプリケーションは
   実際には起動しているのに「did not start」で exit 1 していた。→ `-N` を除去。
2. シナリオ01のリストア先チェックサム照合が認証情報なしの `mariadb` で
   接続し `Access denied for user 'root'@'localhost'`。リストアした datadir は
   primary の権限情報を引き継ぐため root のパスワードが必要。→ `-uroot -ptest` を追加。
3. MariaDB 10.11(Ubuntu 22.04)で mbkeeper が全シナリオ即
   `executable file not found in $PATH`。pip 22.0.2 同梱の setuptools 59.6 が
   本プロジェクトの PEP 621 `[project]` メタデータを読めず、install が中身の
   ない `UNKNOWN-0.0.0` を黙って生成しエントリポイントを作らないため。→
   `--break-system-packages` 付き install が失敗した場合(=22.04)に pip を
   更新(モダンな setuptools も同時に入る)してから再 install するよう
   `replica.Dockerfile` と `run-container.sh` を修正。24.04(11.4)は
   `--break-system-packages` 付きが成功するので pip には触れない。

あわせて CI の action を Node.js 20 廃止対応で最新メジャーへ更新
(checkout@v7 / setup-python@v6 / upload-artifact@v7)。

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
