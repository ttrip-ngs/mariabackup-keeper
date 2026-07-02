# 004 前提チェックとフック (M4)

日付: 2026-07-02

## 実装したもの

- `replication.py`: `check_replication(backup, replication)`。
  `SHOW REPLICA STATUS\G` を `mariadb -e` で実行し「Key: Value」形式の
  出力をパース。`mode=require_replica` で空なら PreconditionError、
  `max_lag_seconds>0` で `Seconds_Behind_Master` が閾値超過または NULL
  (レプリケーション停止中)なら PreconditionError。`SELECT VERSION()` も
  取得して meta.json の `mariadb_version` に反映。
- **設計判断**: `orchestrator.run()` は `mode=off` かつ `max_lag_seconds=0`
  の場合、mariadb クライアントを一切呼ばない
  (`_check_replication_if_configured`)。理由: レプリケーションを気にしない
  単純な単一ノード運用で DB 接続を強制すると、テスト容易性はもちろん
  実運用でも不要な依存になる。一方 `mbkeeper check` は診断コマンドなので
  常に `check_replication` を呼び、疎通そのものを確認する(mode=off でも
  DB 接続失敗はユーザーに見せるべき情報)。この非対称性は意図的。
- `hooks.py`: `run_hook(command, logger, stdin_data, fail_fast)`。
  `shlex.split` でコマンドをパースし(shell=True は使わない)、
  `pre_backup` のみ `fail_fast=True` で呼び出し失敗時に PreconditionError
  を送出、他の3フックは失敗してもログのみで継続。
- `orchestrator.py`:
  - `run()` に `pre_backup`(バックアップ開始前、fail_fast)、
    `post_backup`(取得成功後)、`pre_purge`(purge 直前)、
    `post_run`(**常に最後に実行**。backup 失敗や全保管先失敗でも実行し、
    実行サマリ JSON を stdin で渡す)を組み込み。post_run 呼び出しを
    `_finish()` に集約して 3 箇所の return から重複なく呼べるようにした。
  - **例外**: pre_backup hook 失敗や replication precondition 失敗は
    `run()` 内で catch せず素通りさせ、呼び出し元(cli.py)の
    `except KeeperError` で exit_code=5 にマッピングする。この場合
    post_run は呼ばれない(「run が実際に試行された」と言えるだけの
    状態に達していないため)。
  - `check(config) -> CheckSummary`: mariabackup 存在確認
    (`--version` が失敗しないか)、replication 疎通確認、各保管先の
    `check()` を実行し、`CheckItem` のリストで結果を返す。
- `cli.py`: `check` サブコマンドを追加。`[OK]`/`[FAIL]` 形式で出力し、
  全項目 OK なら exit 0、そうでなければ exit 5(PRECONDITION_FAILED)。

## テスト

- 127 件のユニットテストが全通過(新規: replication 9件、hooks 8件、
  orchestrator hooks/replication 統合 8件、orchestrator check 4件、
  cli check 2件)。
- 手動スモークテストで `mbkeeper check`(replication だけ FAIL、exit 5)
  と `mbkeeper run`(mode=off なので replication 未設定でも成功、exit 0)
  の非対称動作を実機で確認。

## 次にやること(M5)

- docker-compose.yml(primary/replica/store/restore-target)
- tests/integration/run.sh、scenarios 3 本(フルバックアップ+リストア、
  クロスバックアップ、purge)
- GitHub Actions ci.yml(unit: Python 3.9/3.11/3.13 マトリクス、
  integration: MariaDB 10.11/11.4 マトリクス、run.sh を共用)
- ここでようやく実際の mariabackup/rsync/ssh/レプリケーション構成を
  使った end-to-end 検証が入る(M2-M4 はすべてフェイク実行ファイルによる
  ユニットテストのみ)
