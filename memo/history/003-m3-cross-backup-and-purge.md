# 003 クロスバックアップと purge (M3)

日付: 2026-07-02

## 実装したもの

- `retention.py`: `select_purge(stored, keep, grace_hours, now, in_progress_id)`
  純粋関数。complete な世代は backup_id 降順ソートで新しい `keep` 件を保持、
  残りを delete。incomplete(`.partial`/meta.json欠落)は grace_hours 経過後に
  delete、実行中の世代(in_progress_id)は grace を超えても常に keep。
  保管先ごとに独立呼び出しする設計(中央台帳は持たない)。
- `destinations/ssh.py`: SSHDestination。argv 組み立て
  (`build_ssh_argv`/`build_rsync_argv`/`build_rsync_file_argv`)を純粋関数として
  分離し `test_ssh_argv.py` で実 ssh 不要のテストを実現。配置プロトコルは
  local と同じ「partial へ rsync(meta.json除外)→meta.json だけ追加rsync→
  リモートで mv」の順。リモートコマンド実行はすべて `ssh user@host "command"`
  形式の 1 発呼び出し(`_remote_run`)に統一。一覧取得は POSIX sh の
  リモートスクリプト(`stat -c %Y` で mtime 取得、GNU stat 前提=Linux ノード限定、
  macOS の BSD stat では動かないが対象は Linux DB サーバーのみなので許容)。
  `parse_list_output()` を純粋関数として分離。
- ユニットテストでは実ネットワークを使わず、PATH に「リモートコマンドを
  ローカルで実行するだけの fake ssh」を差し込む手法
  (`tests/unit/fakes.py:make_fake_ssh_bin_dir`)で mkdir/test/rm/mv の配線を検証。
  rsync 本体を使った実データ転送(rsync --server プロトコル)は
  fake では検証しない(macOS の BSD stat 差異やプラットフォーム間の
  rsync 挙動差を踏まえ、設計書どおり M5 の Docker 結合試験に委譲)。
- `orchestrator.py`: `purge()`(独立コマンド用、`mbkeeper purge` から呼ぶ)と
  `run()` 内の自動 purge(`_purge_stored_destinations`)を追加。
  **store に失敗した保管先は purge しない**(design 通り、冗長性が
  落ちている状態でさらに削除しない方針)。exit code の優先順位:
  destination 失敗(8)> purge 失敗(9)> 成功(0)。listing 失敗も
  purge 失敗として扱う(見えないものは消さない、が purge 全体としては
  エラー扱い)。
- `cli.py`: `purge`(`--destination` 複数指定、`--dry-run`)、`list`
  (`--destination` 単一指定)サブコマンドを追加。

## 設計判断の記録

- purge 判定の完全性チェックは destination の `list_backups()` が返す
  `StoredBackup.complete` フラグのみに依存し、purge 側では再度ファイル
  システムを見に行かない(責務分離: 何が存在するかは destination の責務、
  何を消すかは retention の責務)。
- ssh destination の delete/check/list はすべて `_remote_run` 経由の
  単発 ssh 呼び出しで、リトライは行わない(rsync のみ `transfer.retries`
  でリトライ。理由: mkdir/rm/mv/test は冪等かつ一瞬で終わるため、
  ネットワーク瞬断以外での失敗はリトライしても状況が変わらないことが多い。
  rsync のみデータ転送量が大きく再開の価値がある)。

## テスト

- 95 件のユニットテストが全通過(retention 9件、ssh argv 8件、
  ssh destination 11件、purge 統合 5件、cli purge/list 4件、既存分含む)。
- ruff check/format 通過。

## 次にやること(M4)

- replication.py(SHOW REPLICA STATUS パース、lag チェック、
  require_replica モードでの実行拒否)
- `mbkeeper check` サブコマンド(設定検証+疎通確認)
- hooks.py(pre_backup/post_backup/pre_purge/post_run)
- meta.json の mariadb_version フィールドを replication.py 経由で埋める
  (M2 では空文字のまま残していた)
