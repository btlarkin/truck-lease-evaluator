# `docs/` — the public landing page

Static landing page for the Truck Lease Evaluator, served by GitHub Pages from this folder.

Plain HTML and CSS. No build step, no npm, no framework, no web fonts, no analytics, no
trackers, no JavaScript. Open `index.html` in a browser and it works.

```
docs/
├── index.html       the page
├── style.css        the only stylesheet
├── CNAME            custom domain — PLACEHOLDER, see below
├── README.md        this file
└── assets/
    ├── favicon.svg / favicon.ico / apple-touch-icon-180.png
    ├── og-1200x630.png                      link-preview image
    ├── waybill-wordmark.svg / -white.svg    header
    └── waybill-lockup-horizontal.svg / -white.svg   footer
```

Every asset is copied from the Waybill Data Systems brand kit. Nothing was redrawn and no path
geometry was touched — the `d` attributes are byte-identical to the masters, verified by diff.

**One edit was made to the four SVGs in this folder:** the build comment naming the registered
legal entity was removed, because this repository is public and the page does not otherwise
name it. Put it back if you want the attribution on the open internet; that is a decision for
you, not for a build script.

The `-white` variants are served to dark-mode viewers via
`<picture><source media="(prefers-color-scheme: dark)">`.

---

## ☤ The hostname is chosen: `lease.waybilldata.com`

Option A below was taken. `CNAME` holds `lease.waybilldata.com`, and `index.html` uses it for
`<link rel=canonical>`, `og:url`, `og:image` and `twitter:image`. The loud placeholder that used
to sit in `<head>` is gone because it has been resolved.

**The DNS record is not in this repo and never can be.** At the registrar holding
`waybilldata.com` (Hostinger, as of 2026-07-27):

| Type | Name | Value |
|---|---|---|
| `CNAME` | `lease` | `btlarkin.github.io.` |

Until that record exists and propagates, GitHub Pages serves a 404 at the custom domain **and
redirects the `github.io` URL to it**, so the site is unreachable at both addresses. That is
expected, not a broken build. Check with:

```bash
dig +short lease.waybilldata.com CNAME     # want: btlarkin.github.io.
```

Enforce HTTPS cannot be ticked until the certificate is issued, which cannot happen until DNS
resolves. Order matters: DNS first, then HTTPS.

---

## ☤ Choosing the hostname

Two options were left open. They are not equivalent and the choice changes `CNAME`.

### Option A — subdomain: `lease.waybilldata.com`

`CNAME` contents:

```
lease.waybilldata.com
```

DNS at the registrar holding `waybilldata.com`:

| Type | Name | Value |
|---|---|---|
| `CNAME` | `lease` | `btlarkin.github.io.` |

Then in **Settings → Pages → Custom domain**, enter `lease.waybilldata.com`, save, wait for the
check to pass, and tick **Enforce HTTPS**.

- Cleanest DNS. A `CNAME` record is all it takes, and the apex is left free for the main site.
- The page is its own property. Nothing about it depends on the main site existing yet.
- Costs the SEO benefit of living under the main domain's path.

### Option B — path on the apex: `waybilldata.com/lease-evaluator`

This one **cannot be done with a `CNAME` file in this repo.** A GitHub Pages project site
serves at `waybilldata.com/truck-lease-evaluator/` — the path is the repo name, and only the
user/org site (`btlarkin.github.io`) may claim the apex. To get `waybilldata.com/lease-evaluator`
you would need one of:

1. Rename this repo to `lease-evaluator`, put the apex `CNAME` on the **`btlarkin.github.io`**
   repo, and let this repo serve as its project path. `docs/CNAME` here should then be
   **deleted**, not filled in.
2. Front the whole domain with a proxy (Cloudflare Workers/Pages, Netlify) that maps
   `/lease-evaluator` to this site.

If you want Option B, **delete `docs/CNAME`** and configure the apex on the user-site repo.
Leaving a `CNAME` in both places makes them fight.

Apex DNS, for reference, if the apex ever points at Pages — four `A` records:

```
185.199.108.153   185.199.109.153   185.199.110.153   185.199.111.153
```

plus the matching `AAAA` records from GitHub's current documentation. **Verify these against
GitHub's docs at the time you set them up** — they have changed before.

**Recommendation: Option A.** One DNS record, no coupling to a site that does not exist yet,
and it is reversible.

---

## ☤ Enabling GitHub Pages

1. **Settings → Pages**
2. **Source:** `Deploy from a branch`
3. **Branch:** `main`, **folder:** `/docs`
4. Save. First build takes a minute or two.
5. Add the custom domain (above), wait for the DNS check, then tick **Enforce HTTPS**.

The site is live at `https://btlarkin.github.io/truck-lease-evaluator/` before any custom
domain is attached. **Check it there first** — the relative asset paths work in both places,
so if it renders on the `github.io` URL, the domain is the only remaining variable.

---

## ☤ There is no email capture, and that is the point

This page **had** an email-capture form for the worksheet. It was removed deliberately, along
with its CSS. Do not put it back without reading this.

The audience is drivers evaluating a lease-purchase — a group that has been sold to badly, by
recruiters, for years, and that reads a signup gate on a "here is how you're being taken
advantage of" page as the beginning of the next pitch. The tool's entire claim to authority is
that it asks nothing of the reader: no cloud, no account, no telemetry, MIT licensed, and now
no address either. A list of a few hundred emails is not worth what it costs in standing with
that specific audience.

The worksheet is delivered three ways, all ungated: **in full on the page itself** (the
`#worksheet` section, styled to be printed and filled in with a pen), via `python worksheet.py`
— a zero-dependency module that runs on stock Python with no `pip install` — and via
`python lease_evaluator.py --worksheet` for anyone who has already installed the tool. None of
them needs an endpoint, a service, or a privacy promise.

The on-page copy is the canonical one for non-technical readers, and it is the one that matters:
most of this audience will never open a terminal. If you edit the worksheet in `worksheet.py`,
edit the HTML to match, or the two drift apart.

*Decision made 2026-07-27, on the market signal report at
`05_Code_Forge/sovereign/counting-house/outputs/content-strategy-truck-lease-evaluator.md`.*

---

## ☤ Repository settings

The repo's `homepageUrl` is currently empty. Set it so the link appears on the repo page and in
GitHub search:

```bash
gh repo edit btlarkin/truck-lease-evaluator --homepage "https://lease.waybilldata.com"
```

Worth doing at the same time:

```bash
gh repo edit btlarkin/truck-lease-evaluator \
  --description "Price a truck lease-purchase like the trading position it actually is." \
  --add-topic trucking --add-topic owner-operator --add-topic monte-carlo \
  --add-topic risk-analysis --add-topic python
```

And add the same link to the top of the root `README.md`, which is where most people will land
first.

---

## ☤ Design notes, so the next edit does not break something

### Audience

An owner-operator on a phone, at a truck stop, on poor signal, possibly tired. Every decision
below follows from that.

- Mobile-first. The layout was **rendered and measured at a 345px layout viewport** (a 360px
  device minus a scrollbar) and scales up at `34rem` and `60rem`. `document.scrollWidth` equals
  the viewport at 345, 485, 753 and 1265px — the page body never scrolls horizontally.
- System font stack only. Zero network requests for fonts.
- Content is complete with JavaScript disabled, because there is no JavaScript.
- Body text is `17px` on mobile — comfortable at arm's length in a cab, and above the 16px
  threshold at which iOS Safari zooms the viewport.
- There are no form controls to size: the page asks for nothing.
- The only two horizontally scrolling regions are `.code-scroll` (the install snippet) and
  `.table-scroll` (the sweep table). Both are self-contained; neither pushes the page.

### Colour and contrast

The palette is Waybill's, and the measured values in the brand guide are respected literally.
Two of them constrain the page more than they first appear:

Every ratio below was recomputed from the sRGB relative-luminance formula against these exact
files, not copied from the guide.

| Pair | Ratio | Consequence |
|---|---|---|
| Carbon `#101418` on Paper `#F4F1EA` | **16.40:1** | All body text, both themes. AAA. |
| Carbon on `--surface` light `#EAE6DD` | 14.85:1 | Text inside cards, quotes, code, the worksheet. |
| Paper on `--surface` dark `#1B2026` | 14.53:1 | Same, dark theme. |
| Muted `#5C5C5C` on Paper | 5.93:1 | Passes. On `--surface` light, 5.37:1. |
| Muted `#A0A0A0` on Carbon | 7.07:1 | Passes. On `--surface` dark, 6.27:1. |
| Button: Paper on Carbon | 16.40:1 | Light theme. Dark theme inverts, same ratio. |
| Signal `#B85C00` on Paper | 4.07:1 | Clears 1.4.11 (3:1). **Fails AA for small text.** |
| Signal on Carbon | 4.02:1 | Clears 1.4.11 (3:1). **Fails AA for small text.** |
| Signal on `--surface` (either theme) | 3.69 / 3.57:1 | Still clears 1.4.11. Bars and borders only. |
| Steel `#767676` on Paper | **4.03:1** | **Fails AA — not used.** Steel's 4.54:1 is against *pure white*, not Paper. |

So:

1. **No text content is set in Signal.** Signal appears only as rules, borders, the tornado
   bars, the button's bottom edge, and the focus ring — all governed by WCAG 1.4.11 non-text
   contrast (3:1), which Signal clears in every combination used here. The single `color:`
   declaration that references Signal is `li::marker` on two lists; a bullet glyph carries no
   information and the list content beside it is full-contrast Carbon/Paper. If you would
   rather be absolutist about it, change those two rules to `var(--ink)` and Signal is then
   used in zero `color` declarations.
2. **Steel is not used at all.** Muted text is `#5C5C5C` on Paper (**5.93:1**) and `#A0A0A0` on
   Carbon (**7.07:1**). This is the one deviation from the brand guide's named colours, and it
   exists because Steel-on-Paper measures 4.03:1 — the guide's 4.54:1 figure is against pure
   white, which never appears on this page.
3. Signal is never a fill behind small text. It cannot carry AA-compliant text in either
   direction — Carbon on Signal is 4.02:1, Paper on Signal 4.08:1. It appears only as rules,
   borders and list markers, never as a background for words.

Dark mode is `prefers-color-scheme` only, no toggle. Both directions are AAA on body text.

### Structure

- One `<h1>`. Every section is `<section aria-labelledby>` with an `<h2>`. No skipped levels.
- The tornado chart is CSS-only: real text for the label, dollar figure and `[YOU]`/`[MKT]` tag,
  with a decorative `aria-hidden` bar. The meaning never depends on colour alone.
- No terminal output is pasted as a `<pre>` block in the body copy. The originals are ~72
  characters wide and unreadable at 360px, so they were transposed into responsive HTML. The
  only `<pre>` is the four-line install snippet, in a horizontal-scroll container.
- The `$1.43 / $2.24 / $0.81` figures and the sweep table are the tool's **illustrative
  defaults**, and the page says so in plain language directly above them. `lease_evaluator.py`
  labels them `ILLUSTRATIVE — numbers are invented`; the page must not imply otherwise.

### Copy

Almost all of it is lifted from the root `README.md` verbatim or near-verbatim. That was the
intent. No claim on this page is unsourced: every figure traces to the README, and there are no
testimonials, no client counts, no case studies, and no social proof of any kind, because there
is none to report.

### Things that are deliberately absent

No analytics, no cookie banner (nothing sets a cookie), no exit-intent popup, no countdown, no
"only N spots left", no fake scarcity, no pre-checked consent box, and **no email capture** —
see the section above on why the form was removed. The worksheet must stay ungated. Do not put
a form in front of it to lift conversions.

---

## ☤ One promise you are now making

The page says: *no cloud, no account, no telemetry, nothing phones home, your contract terms
never leave your machine.*

Nothing enforces that but you. There is no analytics tag, no font CDN, no embedded script and
no form — check that it stays that way. One added tracker makes the whole page a lie, and this
audience is the one most likely to view source and find it.

---

## ☤ Page weight

Measured on the delivered files, uncompressed. GitHub Pages serves gzip/brotli, so the wire
cost is roughly a third of this.

| File | Size |
|---|---|
| `index.html` | 19.2 KB |
| `style.css` | 13.0 KB |
| `waybill-wordmark.svg` (header) | 1.2 KB |
| `waybill-lockup-horizontal.svg` (footer) | 4.2 KB |
| `favicon.svg` | 0.4 KB |
| **First view — 5 requests, total** | **37.9 KB** |

The `-white` logo variants (5.3 KB) are fetched only by dark-mode viewers, and only instead of
their light counterparts — never in addition. `og-1200x630.png` (29.9 KB) is fetched by
link-preview crawlers and **never by a browser rendering the page**. `favicon.ico` and
`apple-touch-icon-180.png` (1.7 KB combined) are fallbacks for older browsers and iOS home-screen
saves.

**Everything in `docs/` on disk: 87.7 KB.** Well inside the 500 KB budget.

Zero external requests. Zero fonts. Zero scripts. Zero cookies.
