# One-Time Setup: The Transcription Key

The benchmark needs one password to work — your **AssemblyAI API key**. This is
the same key that lets CognaSync transcribe audio. It's already set on your
server (Render), but your own computer's Terminal needs its own copy to run the
benchmark locally. This is a 2-minute, one-time thing.

---

## Where to find the key

Either of these:

- **From Render (easiest):** open your Render dashboard → your CognaSync service
  → the **Environment** tab → find the variable named `ASSEMBLYAI_API_KEY` and
  copy its value.
- **From AssemblyAI:** log in at assemblyai.com → your account dashboard → copy
  your API key.

It's a long string of letters and numbers. Treat it like a password — don't
paste it into emails, chats, or commit it to git.

---

## How to use it (simplest version)

1. Open the **Terminal** app.
2. Go to your project folder. Type this and press Enter (adjust the path if your
   project lives somewhere else):
   ```
   cd ~/cognasync-mvp
   ```
3. Paste this line, replacing the part in quotes with your real key, and press
   Enter:
   ```
   export ASSEMBLYAI_API_KEY="paste-your-key-here"
   ```
   (Nothing visible happens — that's normal. The key is now active.)
4. In **that same Terminal window**, run the benchmark:
   ```
   python scripts/benchmark_transcription.py --audio-dir data/benchmark
   ```

That's it.

**Note:** Step 3 only lasts for that one Terminal window. If you close it and
come back later, just paste the `export ...` line again before running.

---

## Optional: make it permanent

If you don't want to paste the key every time, add it to your shell profile once:

```
echo 'export ASSEMBLYAI_API_KEY="paste-your-key-here"' >> ~/.zshrc
```

Close and reopen Terminal, and the key will be set automatically from then on.

---

## If something goes wrong

- **"ASSEMBLYAI_API_KEY is not configured"** → the `export` line wasn't run in
  the same window, or the key was pasted with a typo. Redo step 3.
- **"command not found: python"** → try `python3` instead of `python` in the
  run command.
- **"No (audio, .txt) pairs found"** → you haven't added the recordings yet, or
  the audio file names don't match the script names (e.g. `note01.m4a` must sit
  next to `note01.txt`).
