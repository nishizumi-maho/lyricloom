# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 2.0.x | Yes |
| Older versions | No |

Security fixes are made on the current release line. If you are on an older build, reproduce the issue on 2.0.x before reporting it if you can.

## Report a vulnerability privately

**Do not open a public issue for a security vulnerability.**

Use GitHub's private vulnerability reporting:

<https://github.com/nishizumi-maho/lyricloom/security/advisories/new>

If that form is unavailable, open a minimal public issue that asks for a private contact channel. Do not include vulnerability details, proof-of-concept code, personal data or logs in the public issue.

Please include:

- LyricLoom version (`lyricloom --version`) and how it was installed (installer, portable, source, pipx).
- Operating system and version.
- A description of the issue and its impact.
- Steps to reproduce, ideally with a minimal file or a synthetic example.
- Any relevant log excerpt, with personal paths, lyrics and API keys removed.
- Whether the issue also affects the separate MusicBee Starry Karaoke plugin.

Do not attach copyrighted audio or full lyrics unless you have the right to share them.

## What is in scope

Examples of in-scope issues:

- Code execution, path traversal, unsafe file writes or symlink handling in the app or its workers.
- Command injection in the WSL/worker command construction.
- A way for a malicious audio file, `.lrc` file or lyric page to escape the expected parser behavior and harm the user.
- Model download integrity problems (for example, accepting a file without the intended checksum).
- Exposure of the AssemblyAI API key beyond its documented plain-text storage.
- A dependency vulnerability that is reachable through LyricLoom's normal use.
- A privacy issue where audio or personal data is sent somewhere not described in [docs/privacy.md](docs/privacy.md).

## What is out of scope

- The accuracy of lyric timing, lyric search results or model output. These are quality issues, not security issues.
- Copyright, licensing or takedown requests for lyrics or model weights. Use the normal issue tracker or the upstream rights holder.
- Sites blocking LyricLoom's requests. LyricLoom intentionally respects blocks.
- SmartScreen or antivirus reputation warnings for a new unsigned build. Verify the release checksum and use the normal support channel.
- Vulnerabilities in MusicBee, the Starry Karaoke plugin, AssemblyAI, PyTorch, Qt or another third party that are not caused by LyricLoom's integration. Report them to the upstream project; tell us if LyricLoom's use makes the impact worse.
- Social engineering, physical access or a compromised user account.

The Starry Karaoke plugin is a separate project with its own repository and license. Report plugin-specific vulnerabilities there:

<https://github.com/nishizumi-maho/MusicBee-StarryKaraoke>

## Safe research

When testing:

- Use your own machine, your own files and a test profile (`LYRICLOOM_DATA_DIR`) where possible.
- Do not access, modify or exfiltrate another person's data.
- Do not run denial-of-service tests against public lyrics providers, Hugging Face, GitHub or AssemblyAI.
- Do not upload real user audio to a third party while testing.
- Do not include live API keys in a report. If a key was exposed, revoke it first.

## What to expect

This is a volunteer open-source project. We will acknowledge a report as soon as practical, investigate it, and agree on a disclosure timeline with you. We may ask for a minimal reproduction or a patched-build test. There is no bug bounty.

Please give us a reasonable chance to fix the issue before publishing details. We will credit reporters in the advisory or release notes if they want credit.

## API keys and local data

The optional AssemblyAI key is stored in plain text at:

```text
%LOCALAPPDATA%\LyricLoom\assemblyai.key
```

or in `ASSEMBLYAI_API_KEY`. It is not encrypted. Protect the file with normal Windows/Linux account permissions. If you believe it was exposed, revoke it in the AssemblyAI dashboard and add a new one. Do not commit it to git; the repository's `.gitignore` excludes `assemblyai.key`, but ignored files can still be copied into archives.

Lyrics, transcripts, logs and vocal stems are stored locally as described in [docs/privacy.md](docs/privacy.md). Treat a bug report as potentially public: redact paths, user names and lyrics before posting.

## Dependency and model integrity

LyricLoom downloads executable helpers and large model weights. The project verifies checksums where the upstream publishes a stable one (for example Whisper and the MTL checkpoint) and writes downloads through a `.part` file. If you find a path where a download is accepted without the intended verification, or where a downloaded file is executed unexpectedly, report it privately.

Model licenses are separate from security. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
