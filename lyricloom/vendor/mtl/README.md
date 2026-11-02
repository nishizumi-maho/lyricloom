# LyricsAlignment-MTL (vendored inference code)

This directory contains the inference-only code from
[LyricsAlignment-MTL](https://github.com/jhuang448/LyricsAlignment-MTL) by Jiawen Huang,
licensed under the MIT License (see LICENSE). It is vendored so LyricLoom can run the singing
model in its normal Python environment instead of a separate virtualenv.

The checkpoint itself is not part of this repository; `lyricloom models` downloads
`checkpoint_MTL` on first use.
