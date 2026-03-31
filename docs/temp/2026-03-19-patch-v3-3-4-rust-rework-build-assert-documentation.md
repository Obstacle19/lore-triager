# [PATCH v3 3/4] rust: rework `build_assert!` documentation

- Message-ID: `<20260319121653.2975748-4-gary@kernel.org>`
- Classification: `rust_logic_bug`
- Confidence: `medium`
- Mailing list: `rust-for-linux.vger.kernel.org`
- Published at: `2026-03-19T12:16:47+00:00`
- Author: `Gary Guo <gary@kernel.org>`
- Archive URL: not recorded
- Source path: `data/raw/results-rust-bug.mbox::95`

## Summary

The message describes a Rust logic or state-management bug.

## Evidence

Subject/body signals include bug, issue, panic.

## Original Subject

[PATCH v3 3/4] rust: rework `build_assert!` documentation

## Body Excerpt

```text
From: Gary Guo <gary@garyguo.net> Add a detailed comparison and recommendation of the three types of build-time assertion macro as module documentation (and un-hide the module to render them). The documentation on the macro themselves are simplified to only cover the scenarios where they should be used; links to the module documentation is added instead. Reviewed-by: Yury Norov <ynorov@nvidia.com> Signed-off-by: Gary Guo <gary@garyguo.net> --- rust/kernel/build_assert.rs | 119 ++++++++++++++++++++++++++++-------- rust/kernel/lib.rs | 1 - 2 files changed, 92 insertions(+), 28 deletions(-) diff --git a/rust/kernel/build_assert.rs b/rust/kernel/build_assert.rs index 50b0fc0a80fc..726d0b76ca2b 100644 --- a/rust/kernel/build_assert.rs +++ b/rust/kernel/build_assert.rs @@ -1,6 +1,72 @@ // SPDX-License-Identifier: GPL-2.0 //! Various assertions that happen during build-time. +//! +//! There are three types of build-time assertions that you can use: +//! - [`static_assert!`] +//! - [`const_assert!`] +//! - [`build_assert!`] +//! +//! The ones towards the bottom of the list are more expressive, while the ones towards the top of +//! the list are more robust and trigger earlier in the compilation pipeline. Therefore, you should +//! prefer the ones towards the top of the list wherever possible. +//! +//! # Choosing the correct assertion +//! +//! If you're asserting outside any bodies (e.g. initializers or function bodies), you should use +//! [`static_assert!`] as it is the only assertion that can be used in that context. +//! +//! Inside bodies, if your assertion condition does not depend on any variable or generics, you +//! should use [`static_assert!`]. If the condition depends on generics, but not variables +//! (including function arguments), you should use [`const_assert!`]. Otherwise, use +//! [`build_assert!`]. The same is true regardless if the function is `const fn`. +//! +//! ``` +//! // Outside any bodies +//! static_assert!(core::mem::size_of::<u8>() == 1); +//! // `const_assert!` and `build_assert!` cannot be used here, they will fail to compile. +//! +//! #[inline(always)] +//! fn foo<const N: usize>(v: usize) { +//! static_assert!(core::mem::size_of::<u8>() == 1); // Preferred +//! const_assert!(core::mem::size_of::<u8>() == 1); // Discouraged +//! build_assert!(core::mem::size_of::<u8>() == 1); // Discouraged +//! +//! // `static_assert!(N > 1);` is not allowed +//! const_assert!(N > 1); // Preferred +//! build_assert!(N > 1); // Discouraged +//! +//! // `static_assert!(v > 1);` is not allowed +//! // `const_assert!(v > 1);` is not allowed +//! build_assert!(v > 1); // Works +//! } +//! ``` +//! +//! # Detailed behavior +//! +//! `static_assert!()` is equivalent to `static_assert` in C. It requires `expr` to be a constant +//! expression. This expression cannot refer to any generics. A `static_assert!(expr)` in a program +//! is always evaluated, regardless if the function it appears in is used or not. This is also the +//! only usable assertion outside a body. +//! +//! `const_assert!()` has no direct C equivalence. It is a more powerful version of +//! `static_assert!()`, where it may refer to generics in a function. Note that due to the ability +//! to refer to generics, the assertion is tied to a specific instance of a function. So if it is +//! used in a generic function that is not instantiated, the assertion will not be checked. For this +//! reason, `static_assert!()` is preferred wherever possible. +//! +//! `build_assert!()` is equivalent to `BUILD_BUG_ON`. It is even more powerful than +//! `const_assert!()` because it can be used to check tautologies that depend on runtime value (this +//! is the same as `BUILD_BUG_ON`). However, the assertion failure mechanism can possibly be +//! undefined symbols and linker errors, it is not developer friendly to debug, so it is recommended +//! to avoid it and prefer other two assertions where possible. + +pub use crate::{ + build_assert, + build_error, + const_assert,
```
