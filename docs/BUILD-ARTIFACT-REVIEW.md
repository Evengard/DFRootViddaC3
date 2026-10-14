# Successful CI artifact inspection and subsequent service-worker upgrade

Input: `c3u-build-38529261042-1.zip`, from a GitHub Actions build.

The bundled `DFRoot-C3U-CANDIDATE.apk` passes ZIP integrity, contains exactly
one copy of each of `libbootstrap.so`, `libdfroot.so` and `libdfrootsu.so` for
ARM64, and embeds the same KernelSU `.ko` bytes that appear in the archive.
Its Android APK signing block is present. The source report includes actual
DFRoot v3.1 `ExploitRunner.java` with a UI-independent
`run(Context, IReporter)` API.

That artifact **was built before the service-owned root-worker stage**. Its
native packaging is now correct, but its ADB launcher remains the old
Activity-click design. This repo's v5.3 patchset adds stage 05 to run the
reviewed upstream exploit directly from the foreground service. The next
GitHub Actions build must compile the updated APK. No root operation has been
run by this analysis, and no runtime success is claimed for that new build.

Source pin: DFRoot `v3.1` commit `473b3185fa265c179c98bacc8beb6bd3fed471a9`.
KernelSU Next `v3.4.1` commit `8f902aeb16033024143ae36cf711df902cf02fae`.
The CI module is a **new candidate** (not confirmed identical to your original
working v6 binary). Keep the last manually verified APK/KO as a fallback.
