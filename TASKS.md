# TASKS

mariabackup-keeper の実装タスク一覧。設計は `docs/design.md`(元設計:
`.claude/plans/oss-mutable-willow.md`)を参照。

## M1: リポジトリ基盤

- [x] git init(main ブランチ)、.gitignore、LICENSE(MIT)
- [x] .pre-commit-config.yaml(gitleaks + ruff)
- [x] pyproject.toml(src レイアウト、`mbkeeper` エントリポイント、Python 3.9+)
- [x] exit_codes.py(ExitCode IntEnum)
- [x] errors.py(KeeperError 階層、各例外に exit_code を割当)
- [x] config.py(TOML → frozen dataclass、全キー検証、未知キー拒否、エラー全件収集)
- [x] logging_setup.py(text/json フォーマッタ、run_id フィルタ)
- [x] locking.py(flock 非ブロッキング単一実行ロック)
- [x] ユニットテスト雛形(test_config.py, test_config_load.py, test_locking.py)
- [x] Makefile(test/lint/integration)
- [x] dev ブランチ作成、初回コミット

## M2: 取得と local 配置

- [x] backup.py(MariabackupRunner: argv 組み立て、成否判定、timeout、ログ保存)
- [x] manifest.py(世代 ID 採番、meta.json 読み書き)
- [x] destinations/base.py(Destination ABC、StoredBackup dataclass)
- [x] destinations/local.py
- [x] orchestrator.py(run パイプライン正常系: lock→backup→prepare→store。purge は M3、
      precondition/hooks は M4 で追加)
- [x] cli.py(run サブコマンド、--version。purge/list/check は該当機能の実装時に追加)
- [x] `mbkeeper run` がローカル 1 保管先で通ることを確認(手動スモークテストで確認済み)

## M3: クロスバックアップと purge

- [x] destinations/ssh.py(rsync 経由、partial→rename プロトコル)
- [x] retention.py(select_purge 純粋関数)
- [x] on_destination_failure(continue/abort)の実装(M2 で実装済みのロジックを維持。
      ssh 保管先追加後の複数保管先構成での検証は M5 の結合試験で実施)
- [x] purge/list サブコマンドの実装
- [x] run パイプラインへの自動 purge 組み込み(store 成功した保管先のみ対象)

## M4: 前提チェックとフック

- [x] replication.py(SHOW REPLICA STATUS パース、lag チェック、mode=off かつ
      max_lag_seconds=0 のときは client を一切呼ばない遅延評価)
- [x] check サブコマンド(mariabackup / replication / 各保管先の疎通確認)
- [x] hooks.py(pre_backup/post_backup/pre_purge/post_run。pre_backup のみ
      失敗で実行中断、他は警告ログのみ)
- [x] meta.json の mariadb_version を replication.py 経由で取得(mode=off 時は空文字のまま)

## M5: 結合試験と CI

- [x] docker-compose.yml(primary/replica/store/restore-target)
- [x] tests/integration/run.sh、scenarios 3 本
- [x] .github/workflows/ci.yml(unit + integration マトリクス)
- [ ] **未検証**: この開発環境に Docker が無く実行できていない。初回の
      GitHub Actions 実行、またはローカルに Docker が入った環境での
      `make integration` 実行で動作確認が必要(詳細は memo/history/005 参照)

## M6: ドキュメント

- [ ] README.md(商標免責・責任分界)
- [ ] docs/design.md、configuration.md、exit-codes.md、operations.md
