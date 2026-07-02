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
- [ ] dev ブランチ作成、初回コミット

## M2: 取得と local 配置

- [ ] backup.py(MariabackupRunner: argv 組み立て、成否判定、timeout、ログ保存)
- [ ] manifest.py(世代 ID 採番、meta.json 読み書き)
- [ ] destinations/base.py(Destination ABC、StoredBackup dataclass)
- [ ] destinations/local.py
- [ ] orchestrator.py(run パイプライン正常系: lock→precondition→backup→prepare→store→purge)
- [ ] cli.py(run/purge/list/check サブコマンド、--version)
- [ ] `mbkeeper run` がローカル 1 保管先で通ることを確認

## M3: クロスバックアップと purge

- [ ] destinations/ssh.py(rsync 経由、partial→rename プロトコル)
- [ ] retention.py(select_purge 純粋関数)
- [ ] on_destination_failure(continue/abort)の実装
- [ ] purge/list サブコマンドの実装

## M4: 前提チェックとフック

- [ ] replication.py(SHOW REPLICA STATUS パース、lag チェック)
- [ ] check サブコマンド
- [ ] hooks.py(pre_backup/post_backup/pre_purge/post_run)

## M5: 結合試験と CI

- [ ] docker-compose.yml(primary/replica/store/restore-target)
- [ ] tests/integration/run.sh、scenarios 3 本
- [ ] .github/workflows/ci.yml(unit + integration マトリクス)

## M6: ドキュメント

- [ ] README.md(商標免責・責任分界)
- [ ] docs/design.md、configuration.md、exit-codes.md、operations.md
