# Re: [PATCH v13 1/1] rust: interop: Add list module for C linked list interface

- Message-ID: `<DH6QPWOTC3LG.F0RS2U7GDJDW@nvidia.com>`
- Classification: `rust_unsafe_bug`
- Confidence: `medium`
- Mailing list: `rust-for-linux.vger.kernel.org`
- Published at: `2026-03-19T11:59:42+00:00`
- Author: `Alexandre Courbot <acourbot@nvidia.com>`
- Archive URL: not recorded
- Source path: `data/raw/results-rust-bug.mbox::96`

## Summary

The message points to a Rust unsafe/soundness bug.

## Evidence

Subject/body signals include unsafe.

## Original Subject

Re: [PATCH v13 1/1] rust: interop: Add list module for C linked list interface

## Body Excerpt

```text
On Thu Mar 19, 2026 at 4:24 AM JST, Joel Fernandes wrote: > On Wed, Mar 18, 2026 at 07:57:14PM +0100, Miguel Ojeda wrote: >> On Wed, Mar 18, 2026 at 7:31 PM Joel Fernandes <joelagnelf@nvidia.com> wrote: >> > >> > Anyway, the fix is simple, just need to do // SAFETY*: as Miguel suggests >> > here, instead of // SAFETY: >> > https://lore.kernel.org/all/CANiq72kEnDyUpnWMZmheJytjioeiJUK_C-yQJk77dPid89LExw@mail.gmail.com/ >> >> So, to clarify, I suggested it as a temporary thing we could do if we >> want to use that "fake `unsafe` block in macro matcher" pattern more >> and more. >> >> i.e. if we plan to use the pattern more, then I am happy to ask >> upstream if it would make sense for Clippy to recognize it (or perhaps >> it is just a false negative instead of a false positive, given >> `impl_device_context_deref`), so that we don't need a hacked safety >> tag (Cc'ing Alejandra). >> >> But if we could put it outside, then we wouldn't need any of that. >> Unsafe macros support could help perhaps here, which I have had it in >> our wishlist too (https://github.com/Rust-for-Linux/linux/issues/354), >> but I guess the fake block could still be useful to make only certain >> macro arms unsafe? (Perhaps Rust could allow `unsafe` just at the >> start of each arm for that...). > > Even if I reworked the macro to be outisde, it doesn't work as below, still > need the 'disabled' comment on the macro's generate unsafe { } block below. > > If we don't want the SAFETY*: hack, we could do the following. > > Perhaps, we can file the github bug and also do the below. Once the > github bug is fixed, we could remove the 'disable lint' below. > > Thoughts? > > ---8<----------------------- > > diff --git a/rust/kernel/interop/list.rs b/rust/kernel/interop/list.rs > index 495497f0405e..dfa2e1490202 100644 > --- a/rust/kernel/interop/list.rs > +++ b/rust/kernel/interop/list.rs > @@ -73,7 +73,7 @@ > //! > //! > //! // Create typed [`CList`] from sentinel head. > -//! // SAFETY*: `head` is valid and initialized, items are `SampleItemC` with > +//! // SAFETY: `head` is valid and initialized, items are `SampleItemC` with > //! // embedded `link` field, and `Item` is `#[repr(transparent)]` over `SampleItemC`. > //! let list = clist_create!(unsafe { head, Item, SampleItemC, link }); > //! > @@ -328,17 +328,19 @@ impl<'a, T, const OFFSET: usize> FusedIterator for CListIter<'a, T, OFFSET> {} > /// Refer to the examples in the [`crate::interop::list`] module documentation. > #[macro_export] > macro_rules! clist_create { > - (unsafe { $head:ident, $rust_type:ty, $c_type:ty, $($field:tt).+ }) => {{ > + (unsafe { $head:ident, $rust_type:ty, $c_type:ty, $($field:tt).+ }) => ( > + // SAFETY: disable lint. > + unsafe { {{ > // Compile-time check that field path is a `list_head`. > let _: fn(*const $c_type) -> *const $crate::bindings::list_head = |p| { > // SAFETY: `p` is a valid pointer to `$c_type`. > - unsafe { &raw const (*p).$($field).+ } > + &raw const (*p).$($field).+ > }; > > // Calculate offset and create `CList`. > const OFFSET: usize = ::core::mem::offset_of!($c_type, $($field).+); > // SAFETY: The caller of this macro is responsible for ensuring safety. > - unsafe { $crate::interop::list::CList::<$rust_type, OFFSET>::from_raw($head) } > - }}; > + $crate::interop::list::CList::<$rust_type, OFFSET>::from_raw($head) > + } }}); > } > pub use clist_create; I think I like this, it preserves the expected use of `SAFETY:` without that confusing `*`. The unsafe blocks is a bit larger that it should, be we are in a controlled environment. Even after using the `SAFETY*:` I was still getting errors because the in-macro SAFETY comment wasn't at the right place: warning: unsafe block missing a safety comment --> ../rust/kernel/interop/list.rs:335:17 | 335 | |p| unsafe { &raw const (*p).$($field).+ }; | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | ::: ../rust/kernel/gpu/buddy.rs:527:21 | 527 | let clist = clist_create!(unsafe { | _____________________- 528 | | head, 529 | |
```
