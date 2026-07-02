# 001 プロジェクト初期化 (M1)

日付: 2026-07-02

## 決定事項

- CLI コマンド名は `mbkeeper`。リポジトリ/PyPI 名は `mariabackup-keeper`、
  import パスは `mariabackup_keeper`。
- 設定ファイルは TOML。Python 3.9+ をサポートし、3.9〜3.10 のみ `tomli` に依存
  (3.11+ は stdlib `tomllib`)。それ以外は依存ゼロ(argparse + dataclasses +
  subprocess で完結させる方針)。
- 設計の一次資料は `.claude/plans/oss-mutable-willow.md`(後日 docs/design.md
  に転記予定、M6)。

## 実装したもの

- `src/mariabackup_keeper/`: exit_codes.py, errors.py, config.py,
  logging_setup.py, locking.py
- `config.py` の検証方針: 未知キーは全拒否、エラーは `_Errors` に集約して
  一括報告(1 個直したら次のエラーが出る、を避ける)。全項目 frozen
  dataclass に変換し、以降のコードは dataclass のみに依存させる。
- `[[destinations]]` は type ごとに許可キー集合を切り替え(ssh のみ
  host/user/ssh_key 必須)。`work_dir` とローカル保管先 `path` の重複を
  拒否するチェックをここに実装済み。
- ロックは `fcntl.flock` 非ブロッキング。取得失敗時は `LockError`
  (exit_code=4)。

## 次にやること(M2)

- backup.py の MariabackupRunner(mariabackup 呼び出しの抽象化、§5 の
  argv 順序・成否判定・timeout ハンドリング)
- manifest.py(世代 ID 採番、meta.json)
- destinations/base.py + local.py(Destination ABC)
- orchestrator.py の正常系パイプラインと cli.py
