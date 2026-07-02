# 002 取得と local 配置 (M2)

日付: 2026-07-02

## 実装したもの

- `backup.py`: MariabackupRunner。argv は
  `mariabackup [--defaults-file] [--defaults-extra-file] --backup --target-dir=DIR
  [--safe-slave-backup] <extra_args>` の順で固定。成否判定は
  `returncode == 0 かつ stderr に "completed OK!" を含む` の両方を要求
  (mariabackup は失敗時でも rc=0 を返し得るための防御)。timeout は
  Popen で SIGTERM→10 秒猶予→SIGKILL の順(subprocess.run の timeout は
  即 SIGKILL のため使わなかった)。
- `manifest.py`: backup_id は `{prefix}-{UTC 基本形式ISO}Z`
  (例: full-20260702T180000Z)で辞書順=時系列順。meta.json は
  `dataclasses.fields()` で既知フィールドのみ読み込むため、将来の
  schema_version 追加フィールドを読んでも壊れない。
- `destinations/`: `Destination` ABC + `StoredBackup`。レジストリは
  `destinations/__init__.py` の `DESTINATION_TYPES` 辞書 + `@register("type")`
  デコレータ。`local.py` が `__init__.py` の末尾で import され登録される
  (register 定義後に import するため循環 import は問題なし)。
- `LocalDestination` は設計メモの「rsync で統一しても良い」という案は
  採らず、**stdlib の shutil のみ**で実装(依存ゼロ方針を local にも
  徹底。ssh 保管先は M3 で rsync 必須になる)。配置プロトコルは
  `<id>.partial` へコピー→meta.json 最後にコピー→rename でコミット、
  という設計書の手順をローカルコピーでも踏襲。
- `orchestrator.py`: run パイプラインの正常系。lock→work_dir 残骸掃除→
  backup→prepare→meta.json 書き込み→各保管先へ store→終了コード決定→
  (全滅でなければ)work_dir 削除。**purge は未実装(M3)**、
  **replication 前提チェックと hooks は未実装(M4)**。
  `on_destination_failure` の abort/continue 分岐は実装済みだが、
  M2 時点では保管先が local のみなので実質未検証(M3 で ssh 追加時に検証)。
- `cli.py`: `run` サブコマンドと `--version` のみ実装。purge/list/check は
  該当ロジックが揃う M3/M4 で追加する(スタブは作らない方針)。

## テスト

- `tests/unit/fakes.py`: 実 mariabackup を使わず、Python スクリプトで
  mariabackup の stderr 出力パターン(成功/失敗/ハング)を模倣する
  フェイク実行ファイルを生成するヘルパー。
- 59 件のユニットテストが全通過。ruff check/format も通過。
- 手動スモークテスト: フェイク mariabackup + `mbkeeper run` で
  ローカル 1 保管先への取得→配置→meta.json 生成→終了コード 0 を確認。

## 次にやること(M3)

- destinations/ssh.py(rsync 経由、partial→rename、リトライ)
- retention.py(purge 判定の純粋関数)
- purge/list サブコマンド
- on_destination_failure の abort/continue を ssh 保管先も交えて検証
