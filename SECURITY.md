# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 2.1.x | Yes |
| 2.0.x | No |
| Older versions | No |

Security fixes are made on the current release line. If you are on an older build, reproduce the
issue on 2.1.x before reporting it if you can.

The Starry Karaoke MusicBee plugin ships in the same repository under `musicbee/`; the supported
plugin line is 1.3.x.

## Report a vulnerability privately

**Do not open a public issue for a security vulnerability.**

Use GitHub's private vulnerability reporting:

<https://github.com/nishizumi-maho/lyricloom/security/advisories/new>

If that form is unavailable, open a minimal public issue that asks for a private contact channel. Do
not include vulnerability details, proof-of-concept code, personal data or logs in the public issue.

Please include:

- LyricLoom version (`lyricloom --version`) or Starry Karaoke version, and how it was installed
  (installer, portable, source, pipx, MusicBee plugin ZIP).
- Operating system and version.
- A description of the issue and its impact.
- Steps to reproduce, ideally with a minimal file or a synthetic example.
- Any relevant log excerpt, with personal paths, lyrics and API keys removed.
- Whether the issue affects the LyricLoom app, the Starry Karaoke plugin, or both.

Do not attach copyrighted audio or full lyrics unless you have the right to share them.

## What is in scope

Examples of in-scope issues:

- Code execution, path traversal, unsafe file writes or symlink/junction handling in the app, the
  plugin, the recorder or their workers.
- Command injection in the WSL/worker command construction or the plugin's LyricLoom launch.
- A way for a malicious audio file, `.lrc` file, lyric page, plugin settings file or release asset to
  escape the expected parser behavior and harm the user.
- Model or update download integrity problems (for example, accepting a file without the intended
  checksum or following a redirect outside the allowed hosts).
- A way to make the updater run an unverified installer, or to make the plugin run a different
  executable.
- Exposure of the AssemblyAI API key beyond its documented DPAPI-encrypted (Windows) or mode-0600
  (Linux/macOS) storage.
- A local process or another Windows user reaching the single-instance channel, or a message crossing
  from a test/second profile to the user's running LyricLoom.
- A dependency vulnerability that is reachable through LyricLoom's normal use.
- A privacy issue where audio or personal data is sent somewhere not described in
  [docs/privacy.md](docs/privacy.md).

## What is out of scope

- The accuracy of lyric timing, lyric search results or model output. These are quality issues, not
  security issues.
- Copyright, licensing or takedown requests for lyrics or model weights. Use the normal issue tracker
  or the upstream rights holder.
- Sites blocking LyricLoom's requests. LyricLoom intentionally respects blocks.
- SmartScreen or antivirus reputation warnings for a new unsigned build. Verify the release checksum
  and use the normal support channel.
- Vulnerabilities in MusicBee, AssemblyAI, PyTorch, Qt or another third party that are not caused by
  LyricLoom's integration. Report them to the upstream project; tell us if LyricLoom's use makes the
  impact worse.
- Social engineering, physical access or a compromised user account.

Plugin bugs that are not security issues belong in the normal issue tracker with the **Starry
Karaoke plugin** product selected in the bug template.

## Safe research

When testing:

- Use your own machine, your own files and a test profile (`LYRICLOOM_DATA_DIR`) where possible.
- Do not access, modify or exfiltrate another person's data.
- Do not run denial-of-service tests against public lyrics providers, Hugging Face, GitHub or
  AssemblyAI.
- Do not upload real user audio to a third party while testing.
- Do not include live API keys in a report. If a key was exposed, revoke it first.

## What to expect

This is a volunteer open-source project. We will acknowledge a report as soon as practical,
investigate it, and agree on a disclosure timeline with you. We may ask for a minimal reproduction or
a patched-build test. There is no bug bounty.

Please give us a reasonable chance to fix the issue before publishing details. We will credit
reporters in the advisory or release notes if they want credit.

## API keys and local data

The optional AssemblyAI key is stored at:

```text
%LOCALAPPDATA%\LyricLoom\assemblyai.key
```

or supplied through `ASSEMBLYAI_API_KEY`. On Windows the file is encrypted with DPAPI for the current
user; on Linux/macOS it is created with mode `0600`. A plain-text key file from an older version is
migrated automatically on first read. If you believe the key was exposed, revoke it in the AssemblyAI
dashboard and add a new one. Do not commit it to Git; the repository's `.gitignore` excludes
`assemblyai.key`, but ignored files can still be copied into archives.

Lyrics, transcripts, logs and vocal stems are stored locally as described in
[docs/privacy.md](docs/privacy.md). Treat a bug report as potentially public: redact paths, user names
and lyrics before posting.

## Dependency and download integrity

LyricLoom downloads executable helpers, installers and large model weights. The project verifies
checksums where the upstream publishes a stable one and pins catalog sizes and SHA-256 values in the
source. Model, backend and update downloads go through a `.part` file; the updater additionally
accepts only HTTPS URLs from this project's own GitHub release and GitHub's release asset hosts, and
re-hashes the installer before launching it.

If you find a path where a download is accepted without the intended verification, where a redirect
leaves the allowed hosts, or where a downloaded file is executed unexpectedly, report it privately.

Model licenses are separate from security. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
