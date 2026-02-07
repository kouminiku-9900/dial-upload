# Retro Dial-Up Transfer

Windows と macOS 間で、`dial-up` 風の演出を楽しみながらファイル転送するミニアプリです。

- LANモード（TCP）
- Acousticモード（スピーカー送信 + マイク受信）
- わざと遅い転送速度の演出
- GUI あり（ワンクリック起動/停止スターター付き）
- 音声モードのリアルタイム表示:
  - 送信プログレスバー
  - 受信ランプ（赤/黄/緑）
  - ライブ擬似データ文字列
  - ライブ簡易スペアナ表示

## 必要環境

- Python 3.10+
- Windows / macOS
- Acoustic モードでマイク録音する場合: `pip install sounddevice`

## GUI（おすすめ）

### Windows

- 起動: `start_gui_win.bat`
- 停止: `stop_gui_win.bat`

### macOS

- 起動: `start_gui_mac.command`
- 停止: `stop_gui_mac.command`

GUI では `Transport` を `lan` / `acoustic` から選べます。
音声モード利用時は GUI の `Acoustic Passphrase` を送受信で一致させてください。

## LANモード（CLI）

### 受信側

```bash
python3 dialup_transfer.py receive --port 5050 --out-dir received --speed-kbps 42 --chaos
```

### 送信側

```bash
python3 dialup_transfer.py send --host 192.168.x.x --port 5050 --file ./photo.zip --speed-kbps 42 --chaos
```

## Acousticモード（CLI）

### 事前設定（推奨）

共有パスフレーズを送受信で合わせて設定してください。

```bash
export DIALUP_PASSPHRASE='your-shared-secret'
```

### 1) 受信側（マイク録音）

```bash
python3 dialup_transfer.py acoustic-receive --out-dir received --record-seconds 30 --passphrase-env DIALUP_PASSPHRASE
```

### 2) 送信側（スピーカー再生）

```bash
python3 dialup_transfer.py acoustic-send --file ./photo.zip --passphrase-env DIALUP_PASSPHRASE
```

- まず受信側を録音開始してから、送信側を再生してください。
- ノイズに弱いので、最初は短いファイルでテスト推奨です。
- 既定の音声ペイロード上限は 2MB です（`--max-acoustic-bytes` で調整可、最大 16MB）。
- 互換性目的で未認証フレームを許可する場合のみ `--allow-unauthenticated` を使ってください（非推奨）。

### WAV経由のデバッグ

送信WAVだけ作る:

```bash
python3 dialup_transfer.py acoustic-send --file ./photo.zip --no-play --wav-out tx.wav --passphrase-env DIALUP_PASSPHRASE
```

WAVを直接デコード:

```bash
python3 dialup_transfer.py acoustic-receive --wav-in tx.wav --out-dir received --passphrase-env DIALUP_PASSPHRASE
```

## Tips

- もっと遅くしたい: `--baud 40`
- 安定寄り: `--baud 100` と音量調整
- LANは `--speed-kbps 9.6` で超低速演出

## 注意

- Acousticモードは遊び用途の簡易実装です。周囲ノイズやスピーカー/マイク品質で成功率が変わります。
- 音声モードを常用するなら、`--passphrase` / `--passphrase-env` を必ず設定してください。
- `--allow-unauthenticated` はデバッグ互換用です。攻撃者が偽フレームを注入できるため常用しないでください。
- 実用性優先なら LAN モードを使ってください。
