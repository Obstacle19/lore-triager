# Re: [PATCH] rust: regulator: do not assume that regulator_get() returns non-null

- Message-ID: `<177435771478.81121.14256327316446596627.b4-ty@b4>`
- Classification: `rust_memory_safety_bug`
- Confidence: `medium`
- Mailing list: `rust-for-linux.vger.kernel.org`
- Published at: `2026-03-24T13:08:34+00:00`
- Author: `Mark Brown <broonie@kernel.org>`
- Archive URL: not recorded
- Source path: `data/raw/results-rust-bug.mbox::37`

## Summary

The message points to a Rust memory-safety or nullness bug.

## Evidence

Subject/body signals include assume that, do not assume, non-null, returns non-null.

## Original Subject

Re: [PATCH] rust: regulator: do not assume that regulator_get() returns non-null

## Body Excerpt

```text
On Tue, 24 Mar 2026 10:49:59 +0000, Alice Ryhl wrote: > rust: regulator: do not assume that regulator_get() returns non-null Applied to https://git.kernel.org/pub/scm/linux/kernel/git/broonie/regulator.git for-7.0 Thanks! [1/1] rust: regulator: do not assume that regulator_get() returns non-null https://git.kernel.org/broonie/regulator/c/8121353a4bf8 All being well this means that it will be integrated into the linux-next tree (usually sometime in the next 24 hours) and sent to Linus during the next merge window (or sooner if it is a bug fix), however if problems are discovered then the patch may be dropped or reverted. You may get further e-mails resulting from automated or manual testing and review of the tree, please engage with people reporting problems and send followup patches addressing any issues that are reported if needed. If any updates are required or you are submitting further changes they should be sent as incremental updates against current git, existing patches will not be replaced. Please add any relevant lists and maintainers to the CCs when replying to this mail. Thanks, Mark
```
