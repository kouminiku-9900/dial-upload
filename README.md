# Retro Dial-Up Transfer

Windows と macOS 間で、`dial-up` 風の演出を楽しみながらファイル転送するミニアプリです。

- ローカルネットワーク (LAN) で動作
- 送受信ともに Python 標準ライブラリのみ
- あえて遅い転送速度 (`--speed-kbps`) を設定可能
- `--chaos` でランダム遅延・ビープ音の懐かし演出
- GUI あり（ワンクリック起動/停止スターター付き）

## 必要環境

- Python 3.10+
- Windows / macOS / Linux

## GUI（おすすめ）

### Windows

- 起動: `start_gui_win.bat`
- 停止: `stop_gui_win.bat`

### macOS

- 起動: `start_gui_mac.command`
- 停止: `stop_gui_mac.command`

`start` をダブルクリックすると GUI が起動します。

## CLI 使い方

### 1) 受信側を起動（例: Mac 側）

```bash
python3 dialup_transfer.py receive --port 5050 --out-dir received --speed-kbps 42 --chaos
```

起動後、`Share this address with sender: 192.168.x.x:5050` の表示を送信側へ共有します。

### 2) 送信側からファイル送信（例: Windows 側）

```bash
python3 dialup_transfer.py send --host 192.168.x.x --port 5050 --file ./photo.zip --speed-kbps 42 --chaos
```

## Tips

- もっと遅くする: `--speed-kbps 9.6`
- 少し快適にする: `--speed-kbps 128`
- `--chaos` なしにすると安定転送

## トラブルシュート

- 接続できない場合:
  - 送受信端末が同じネットワークにいるか確認
  - ポート `5050` が OS ファイアウォールで許可されているか確認
- 受信ファイルが重複した場合:
  - `file.txt`, `file_1.txt`, `file_2.txt` のように自動採番されます

## 次ステップ案

- GUI をさらにレトロ演出強化（接続音、CRT風エフェクト）
- QR コードで送信先 IP を簡単共有
- E2E 暗号化とワンタイム合言葉
