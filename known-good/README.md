# Optional known-good v6 module

You can put the exact v6 module that you already confirmed working on the C3U here, named `working-v6.ko`. Add its SHA-256 (64 hex characters) to `working-v6.sha256` using `shasum -a 256 working-v6.ko | awk '{print $1}' > working-v6.sha256`. Commit both if you want a reproducible **known-good** build in addition to automated candidate builds.

The default GitHub Actions build checks out KernelSU Next from `config/upstreams.json` and builds a NEW, **not device-verified** candidate. It does not silently switch to this optional file. To select the known-good file in a manual GitHub Actions run, choose **Build** → **Run workflow** → `use_known_good: true`. That mode verifies the SHA and embeds exactly these bytes, but it does not validate the new KernelSU Next release.

Never commit signing credentials or device secrets. Do not assume a rebuilt module with identical structure offsets is device-tested.
