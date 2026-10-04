# Model and provider icons

The Services selectors use local assets through
`murmur.provider_icons.provider_icon(model_or_provider, size=20)`. Loading a
mark never reads configuration, credentials, model weights, or the network.
The adjacent model name remains the source of identity; an icon is only a
recognition aid. Brand names and marks remain owned by their respective owners.
Their use identifies a selectable model or provider and implies no endorsement
of MurMur.

## Official marks

Sources were checked on 2026-10-04. Only assets from the official provider's
site or repository were downloaded. No logo aggregator was used.

| Local asset | Official source | Terms retained | Adaptation |
| --- | --- | --- | --- |
| `qwen.png` | [Qwen-Agent favicon](https://github.com/QwenLM/Qwen-Agent/blob/28ec4a3f8bb3f070a914b26baaf2482a014c16f9/qwen-agent-docs/website/public/favicon.png), revision `28ec4a3f8bb3f070a914b26baaf2482a014c16f9` | Official Qwen-Agent repository's Apache-2.0 [LICENSE](https://github.com/QwenLM/Qwen-Agent/blob/28ec4a3f8bb3f070a914b26baaf2482a014c16f9/LICENSE), copied as `LICENSE.qwen.txt` | Original 406 x 406 PNG, unchanged. Used as the Qwen family mark, including Qwen3-ASR; it is not presented as a separate ASR engine logo. |
| `deepseek.svg` | [DeepSeek-LLM logo](https://github.com/deepseek-ai/DeepSeek-LLM/blob/f8b3d77beb4449d77932eccc6abe08826ad3c608/images/logo.svg), revision `f8b3d77beb4449d77932eccc6abe08826ad3c608` | Official repository's MIT [LICENSE-CODE](https://github.com/deepseek-ai/DeepSeek-LLM/blob/f8b3d77beb4449d77932eccc6abe08826ad3c608/LICENSE-CODE), copied as `LICENSE.deepseek.txt` | The whale symbol's existing path and `#4D6BFE` fill were extracted from the wordmark lockup, with a small clear-space viewBox. The original lockup is retained as `deepseek-source.svg`. |
| `ollama.svg` | [Ollama documentation mark](https://github.com/ollama/ollama/blob/3d99d9779a2b095bfb1e5a025b990b835e89b829/docs/ollama-logo.svg), revision `3d99d9779a2b095bfb1e5a025b990b835e89b829` | Official repository's MIT [LICENSE](https://github.com/ollama/ollama/blob/3d99d9779a2b095bfb1e5a025b990b835e89b829/LICENSE), copied as `LICENSE.ollama.txt` | The original black SVG mascot sits on a light, rounded display badge so it remains visible on MurMur's dark surfaces. The path data, proportions, and black fill are unchanged; original bytes are retained as `ollama-source.svg`. |
| `openai.svg` | [Official OpenAI favicon](https://openai.com/favicon.svg), downloaded 2026-10-04 | [OpenAI design guidelines and marks usage terms](https://openai.com/brand/) | The official light-scheme CSS variables were resolved to their supplied white background and black Blossom fills because Qt SVG does not render the original CSS variables. The shape, placement and proportions are unchanged. Original bytes are retained as `openai-source.svg`. |

Repository licenses are retained with the artwork; they do not transfer
ownership of trademarks. The OpenAI mark is monochrome, secondary to MurMur's
branding, and used only for identified OpenAI models or providers. An
"OpenAI-compatible" transport alone receives a neutral model icon because its
configured model can come from another provider.

## Neutral engine and selection glyphs

No independently licensed, official engine-specific mark was verified for
SenseVoice, Paraformer or Fun-ASR. Those engines therefore receive distinct
neutral glyphs authored for MurMur rather than another engine's logo.

| Selection | Asset | Meaning |
| --- | --- | --- |
| SenseVoice | `sensevoice-neutral.svg` | Sound wave |
| Paraformer | `paraformer-neutral.svg` | Microphone |
| Fun-ASR / FunASR | `funasr-neutral.svg` | Speech bubble and sound wave |
| Bailian / DashScope / Aliyun NLS | `cloud-speech-neutral.svg` | Cloud speech; not an Alibaba or Qwen brand mark |
| Unknown speech engine / offline speech | `speech-neutral.svg` | Generic transcription |
| Auto (local) / local model | `local-neutral.svg` | Local computer, without assuming an installed model or runtime |
| Unknown configurable model | `model-neutral.svg` | Generic model |

These grey line glyphs are MurMur interface artwork, not official model marks.
Their `#8793a5` strokes retain contrast on both light and dark surfaces. Official
Ollama and OpenAI marks have light display backgrounds for dark-mode visibility.
In a combined label such as `Ollama / Qwen3:4b`, the model family takes
precedence over its serving runtime. Unknown models are never assigned a
recognizable provider mark by guessing an endpoint.

## Local resources and packaging

Assets resolve relative to `provider_icons.py`, which works in the source tree,
an installed wheel, and PyInstaller's packaged `murmur` directory. The current
Hatch wheel configuration selects the entire `murmur` package, which includes
these non-Python files by default ([Hatch file selection](https://hatch.pypa.io/latest/config/build/#packages)).
The PyInstaller spec includes `collect_data_files('murmur',
includes=['assets/providers/*'])`. Licenses and retained source SVGs must travel
with the runtime assets. No portable build was run; the project's existing
portable security block remains in force.

`tests/test_provider_icons.py` checks family and neutral mapping, local
attribution files, the absence of external SVG resources, and nonempty Qt
rendering at the 20-pixel menu size, including the actual dark surfaces
`#242428` and `#252429`. It detects unsupported SVG styling that parses but
paints no visible mark and verifies that Ollama's display badge preserves its
original black path. Contact sheets were visually checked on light and dark
backgrounds at 20 and 40 pixels.

## Asset SHA256

| File | SHA256 |
| --- | --- |
| `qwen.png` | `d54559fff2fe10123bd3cf9a7c91bb696060de04cc68ee5d561f1c070f54e269` |
| `deepseek-source.svg` | `ac13bdc805820c46bf0faf053aa5d31f72b051794abfe1dd72a682f09de2966b` |
| `deepseek.svg` | `16269b7ac09fb917c018ee4c6d73dbb1140087f2cb3890d6aa66e39b4db6e425` |
| `ollama-source.svg` | `397a6ee071cce1496edd8a86dd1c91ce005712ec161690e411b3dc7f151181f5` |
| `ollama.svg` | `4a0f9f30aa21b8638b6ff72b4ed8c06ac0633be7a24ebc46d3356a1bc776f8cb` |
| `openai-source.svg` | `ed615b8fd9703863918daae6106396a42926fd167abc1bcad4aca860ff0f7ba6` |
| `openai.svg` | `247c2f76cdd8b5e02bacbd3f46107da43ff93f157995e6123a1cd4e249a7a6ec` |
