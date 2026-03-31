# ✓ i915.CI.BAT: success for rust: interop: Add list module for C linked list interface (rev4)

- Message-ID: `<177395813805.377450.11487247458474282015@a3b018990fe9>`
- Classification: `rust_logic_bug`
- Confidence: `medium`
- Mailing list: `intel-gfx.lists.freedesktop.org`
- Published at: `2026-03-19T22:08:58+00:00`
- Author: `Patchwork <patchwork@emeril.freedesktop.org>`
- Archive URL: not recorded
- Source path: `data/raw/results-rust-bug.mbox::91`

## Summary

The message describes a Rust logic or state-management bug.

## Evidence

Subject/body signals include bug, issue, race, regression.

## Original Subject

✓ i915.CI.BAT: success for rust: interop: Add list module for C linked list interface (rev4)

## Body Excerpt

```text
== Series Details == Series: rust: interop: Add list module for C linked list interface (rev4) URL : https://patchwork.freedesktop.org/series/162792/ State : success == Summary == CI Bug Log - changes from CI_DRM_18177 -> Patchwork_162792v4 ==================================================== Summary ------- **SUCCESS** No regressions found. External URL: https://intel-gfx-ci.01.org/tree/drm-tip/Patchwork_162792v4/index.html Participating hosts (42 -> 39) ------------------------------ Missing (3): bat-dg2-13 fi-snb-2520m bat-adls-6 Known issues ------------ Here are the changes found in Patchwork_162792v4 that come from known issues: ### IGT changes ### #### Issues hit #### * igt@i915_selftest@live@workarounds: - bat-mtlp-9: [PASS][1] -> [DMESG-FAIL][2] ([i915#12061]) +1 other test dmesg-fail [1]: https://intel-gfx-ci.01.org/tree/drm-tip/CI_DRM_18177/bat-mtlp-9/igt@i915_selftest@live@workarounds.html [2]: https://intel-gfx-ci.01.org/tree/drm-tip/Patchwork_162792v4/bat-mtlp-9/igt@i915_selftest@live@workarounds.html #### Possible fixes #### * igt@i915_selftest@live: - bat-mtlp-8: [DMESG-FAIL][3] ([i915#12061]) -> [PASS][4] +1 other test pass [3]: https://intel-gfx-ci.01.org/tree/drm-tip/CI_DRM_18177/bat-mtlp-8/igt@i915_selftest@live.html [4]: https://intel-gfx-ci.01.org/tree/drm-tip/Patchwork_162792v4/bat-mtlp-8/igt@i915_selftest@live.html - bat-dg2-8: [DMESG-FAIL][5] ([i915#12061]) -> [PASS][6] +1 other test pass [5]: https://intel-gfx-ci.01.org/tree/drm-tip/CI_DRM_18177/bat-dg2-8/igt@i915_selftest@live.html [6]: https://intel-gfx-ci.01.org/tree/drm-tip/Patchwork_162792v4/bat-dg2-8/igt@i915_selftest@live.html * igt@i915_selftest@live@workarounds: - bat-dg2-9: [DMESG-FAIL][7] ([i915#12061]) -> [PASS][8] +1 other test pass [7]: https://intel-gfx-ci.01.org/tree/drm-tip/CI_DRM_18177/bat-dg2-9/igt@i915_selftest@live@workarounds.html [8]: https://intel-gfx-ci.01.org/tree/drm-tip/Patchwork_162792v4/bat-dg2-9/igt@i915_selftest@live@workarounds.html [i915#12061]: https://gitlab.freedesktop.org/drm/i915/kernel/-/issues/12061 Build changes ------------- * Linux: CI_DRM_18177 -> Patchwork_162792v4 CI-20190529: 20190529 CI_DRM_18177: 242f4d8af4c4708eabb93e79949d45caec8d4354 @ git://anongit.freedesktop.org/gfx-ci/linux IGT_8811: cc3169e72592a56b806ce54a87060519151ad5fe @ https://gitlab.freedesktop.org/drm/igt-gpu-tools.git Patchwork_162792v4: 242f4d8af4c4708eabb93e79949d45caec8d4354 @ git://anongit.freedesktop.org/gfx-ci/linux == Logs == For more details see: https://intel-gfx-ci.01.org/tree/drm-tip/Patchwork_162792v4/index.html
```
