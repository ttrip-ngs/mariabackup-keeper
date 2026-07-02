# 006 ドキュメント整備 (M6)

日付: 2026-07-02

## 実装したもの

- `README.md`: プロジェクト概要、Status(結合試験が未実行である旨を明記)、
  Why(Holland 等との差別化)、インストール、クイックスタート、CLI一覧、
  アーキテクチャ概要、テスト戦略、責任分界(README に明記する契約要件を
  満たす)、ライセンス、商標免責を含む。商標免責は冒頭に一行 + 末尾に
  正式な節の二段構え。
- `docs/design.md`: モジュール責務表、Destination 抽象化と配置プロトコル、
  purge の設計方針、クロスバックアップと failure policy、将来拡張点の表。
  実装済みコードの構造(モジュール名・関数シグネチャ)に合わせて記述
  (設計時点の `.claude/plans/oss-mutable-willow.md` とは若干の差分があり、
  実装が正)。
- `docs/configuration.md`: `config.py` の実装(バリデーションルール含む)
  と完全に一致させた全項目リファレンス。特に `[replication]` の
  「mode=off かつ max_lag_seconds=0 のときは DB 接続しない」という
  非自明な挙動を明記。
- `docs/exit-codes.md`: `exit_codes.py` の `ExitCode` と1対1対応する表、
  監視での重要度分類(page/warn/ignore)を追記。
- `docs/operations.md`: cron/systemd timer 設定例、専用ユーザーでの運用、
  SSH 鍵セットアップ(`rrsync` によるコマンド制限を含む推奨手順)、
  認証情報の扱い、リストア訓練についての注意。

## 設計判断の記録

- README の「責任分界」節は元の設計指示書の要求
  (「本番でのリストア試験は利用者の責務」を明記)をそのまま反映。
  CI が担保する範囲(代表的構成での論理的正しさ)と、利用者が負う範囲
  (実データでのリストア検証)を明確に切り分けた。
- docs/design.md は `.claude/plans/oss-mutable-willow.md`(元設計指示書)の
  丸写しではなく、実装完了後の状態を正として書き直した。理由:
  設計時点の想定と実装で異なった判断(例: local destination は rsync
  ではなく shutil を使う、replication チェックは mode=off 時は省略する
  等)がいくつかあり、それらをそのまま反映した方が今後の開発者にとって
  正確な一次資料になる。

## プロジェクト全体の状態(M1-M6 完了時点)

- ユニットテスト 127 件、全通過。ruff check / format 通過。
- Docker 結合試験(M5)は環境制約により未実行。次のセッションまたは
  ユーザーの Docker 環境で最初の実行確認が必要。
- 6 マイルストーンすべてに着手・完了。feature ブランチはすべて dev への
  マージ後に削除済み。main へのリリース PR はまだ作成していない
  (ユーザーの指示があれば次のステップ)。
