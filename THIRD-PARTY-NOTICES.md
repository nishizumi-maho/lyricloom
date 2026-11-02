# Third-party notices

LyricLoom is licensed under the **GNU General Public License, version 3 or later** (see [LICENSE](LICENSE)). It depends on third-party software, model weights and dictionaries that keep their own licenses.

This file lists the components that matter for distribution and for commercial use. It is **not legal advice**. If you redistribute LyricLoom, a build of it, or a model bundle, check the exact license texts shipped with the versions you use.

## The important restrictions

### MMS_FA is non-commercial

The default multilingual forced-alignment model, **MMS_FA**, is distributed by Meta/Fairseq and exposed through torchaudio. Its weights are **CC-BY-NC 4.0 (Attribution-NonCommercial 4.0 International)**.

That is a restriction on the **model weights**, not on LyricLoom's GPL source code. If you use LyricLoom's default CTC alignment path for a commercial purpose, you need a different license or a different alignment model. LyricLoom's GPL license does not grant commercial rights to MMS_FA.

### Mel-Band RoFormer weights

The Mel-Band RoFormer architecture and the `audio-separator` code are open source, but the **checkpoint** (`vocals_mel_band_roformer.ckpt`) comes from a model registry and its license is not declared consistently in this repository. Check the upstream model card and the audio-separator registry entry before commercial use or redistribution. Do not assume the code license covers the weights.

### PySide6 / Qt is LGPL, not GPL

LyricLoom uses PySide6 under the **LGPL-3.0**. The Qt libraries are dynamically linked; do not statically link them or modify them without complying with the LGPL's relinking and source-availability requirements. The PySide6/Qt source is available from the Qt project.

## Runtime components

| Component | License | Used for | Source |
|---|---|---|---|
| **PySide6 / shiboken6 / Qt** | LGPL-3.0 (also GPL-2.0/3.0 or commercial) | Desktop UI, multimedia | <https://www.qt.io/qt-for-python> |
| **pykakasi** | GPL-3.0-or-later | Japanese romanization | <https://github.com/miurahr/pykakasi> |
| **mutagen** | GPL-2.0-or-later | Audio tag reading | <https://github.com/quodlibet/mutagen> |
| **Unidecode** | GPL-2.0-or-later | Latin transliteration in text handling | <https://pypi.org/project/Unidecode/> |
| **fugashi** | MIT AND BSD-3-Clause | MeCab wrapper for Japanese | <https://github.com/polm/fugashi> |
| **ipadic** | NAIST license | Japanese dictionary | IPADIC / NAIST |
| **soxr** | LGPL-2.1-or-later | High-quality resampling | <https://github.com/dofuuz/python-soxr> |
| **soundfile** | BSD-3-Clause | Reading/writing WAV/FLAC | <https://github.com/bastibe/python-soundfile> |
| **libsndfile** | LGPL-2.1-or-later | Audio file I/O behind soundfile | <https://libsndfile.github.io/libsndfile/> |
| **numpy** | BSD-3-Clause | Numeric arrays | <https://numpy.org> |
| **scipy** | BSD-3-Clause | Signal processing and least-squares fit | <https://scipy.org> |
| **librosa** | ISC | Audio loading/resampling helpers | <https://github.com/librosa/librosa> |
| **rapidfuzz** | MIT | Fuzzy text matching | <https://github.com/rapidfuzz/RapidFuzz> |
| **httpx** | BSD-3-Clause | HTTP client | <https://github.com/encode/httpx> |
| **beautifulsoup4** | MIT | HTML parsing for lyric pages | <https://www.crummy.com/software/BeautifulSoup/> |
| **NLTK** | Apache-2.0 | g2p_en corpora and tokenization | <https://www.nltk.org> |
| **g2p_en** | Apache-2.0 | English grapheme-to-phoneme for MTL | <https://github.com/Kyubyong/g2p> |
| **inflect** | MIT | English number/word inflection | <https://github.com/jaraco/inflect> |
| **imageio-ffmpeg** | BSD-2-Clause | Bundled ffmpeg discovery | <https://github.com/imageio/imageio-ffmpeg> |
| **FFmpeg** | LGPL-2.1-or-later or GPL-2.0-or-later, depending on the build | Audio decode/encode | <https://ffmpeg.org> |
| **PyInstaller** | GPL-2.0-or-later with a special exception for bootloaders | Release builds (development tool) | <https://pyinstaller.org> |

`pykakasi`, `mutagen` and `Unidecode` are GPL-licensed dependencies. Their licenses are compatible with LyricLoom's GPL-3.0-or-later. `PySide6` is used under the LGPL, not the GPL option.

## Machine-learning components

| Component | License | Role | Source |
|---|---|---|---|
| **OpenAI Whisper** (large-v3 weights) | MIT | Speech model weights | <https://github.com/openai/whisper> |
| **whisper.cpp** | MIT | Local Whisper inference | <https://github.com/ggml-org/whisper.cpp> |
| **LyricsAlignment-MTL** | MIT | English singing-model alignment code and checkpoint | <https://github.com/jhuang448/LyricsAlignment-MTL> |
| **audio-separator** | MIT | Vocal separation wrapper | <https://github.com/nomadkaraoke/python-audio-separator> |
| **Mel-Band RoFormer architecture** | MIT | Vocal separation model architecture | See the Audio Separator / Mel-Band RoFormer projects |
| **Mel-Band RoFormer checkpoint** | **Check upstream** | Vocal separation weights | audio-separator model registry |
| **MMS_FA** | **CC-BY-NC 4.0** | Multilingual CTC forced alignment | <https://pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html> |
| **PyTorch** | BSD-3-Clause | Tensor/GPU runtime | <https://github.com/pytorch/pytorch> |
| **torchaudio** | BSD-2-Clause | MMS_FA pipeline and audio ops | <https://github.com/pytorch/audio> |

### Model download licenses

Downloading a model does not change its license. The LyricLoom GPL applies to LyricLoom's source, not to the weights:

- **Whisper large-v3:** MIT. The whisper.cpp inference code is MIT.
- **MMS_FA:** CC-BY-NC 4.0. Non-commercial. This is the default alignment path for non-English songs and the fallback for English.
- **Mel-Band RoFormer checkpoint:** verify the upstream model card. The repository does not relicense it.
- **LyricsAlignment-MTL:** the inference code is MIT; check the upstream checkpoint terms if you redistribute it.
- **NLTK corpora:** each data package has its own terms; see the NLTK data index.

If you publish a Windows installer or portable ZIP that includes models, include this file and the upstream license texts, and make sure the model licenses allow your distribution. If you cannot satisfy the non-commercial MMS_FA terms, ship a build without MMS_FA or provide a licensed alternative.

## Development-only components

These are not part of the runtime application:

| Component | License |
|---|---|
| pytest | MIT |
| pytest-qt | MIT |
| ruff | MIT |
| PyInstaller | GPL-2.0-or-later with bootloader exception |

## Separately licensed companion

**Starry Karaoke for MusicBee** is a separate project:

<https://github.com/nishizumi-maho/MusicBee-StarryKaraoke>

It is MIT-licensed and is not bundled with LyricLoom. Its NMeCab, IPADic and RomajiCore components keep their own licenses, included in its release ZIP. LyricLoom's GPL does not apply to the plugin, and the plugin's MIT license does not apply to LyricLoom.

## Trademarks

OpenAI, Whisper, Qt, PySide6, PyTorch, MusicBee, AMD, Radeon, NVIDIA, Windows and other names are trademarks of their respective owners. LyricLoom is not affiliated with or endorsed by any of them.

## Source and license texts

- LyricLoom's full GPL text: [LICENSE](LICENSE).
- Each Python dependency ships its license metadata in its package; the upstream links above are the authoritative source.
- Model weights are downloaded separately; their license cards travel with the upstream repository or model registry.

If you believe a component is missing from this list, please open an issue at <https://github.com/nishizumi-maho/lyricloom/issues> with the component, version and license. This file is maintained to make redistribution safer, not to provide legal advice.
