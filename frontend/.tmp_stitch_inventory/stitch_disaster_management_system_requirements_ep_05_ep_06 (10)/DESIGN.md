# Design System Specification: The Architectural Minimalist

## 1. Overview & Creative North Star
**Creative North Star: "The Digital Monolith"**

This design system is not a template; it is an architectural framework. Inspired by the precision of high-end editorial design and the functional clarity of modern AI interfaces, it prioritizes **content as the primary UI element**. 

By stripping away the "noise" of traditional digital interfaces—heavy shadows, vibrant gradients, and rigid dividers—we create a workspace that feels like a quiet, high-end gallery. We break the "generic SaaS" look through **Intentional Asymmetry** (e.g., staggering content blocks) and **Tonal Depth**, where hierarchy is communicated through the physical stacking of grayscale surfaces rather than lines.

---

## 2. Colors & Surface Logic
The palette is strictly monochromatic, utilizing the full breadth of the Material Design scale to create a "paper-on-glass" aesthetic.

### The "No-Line" Rule
To achieve a premium feel, **1px solid borders are prohibited for sectioning.** Boundaries must be defined solely through background color shifts. For example, a sidebar should use `surface_container_low` (#f3f3f4) against a main content area of `surface` (#f9f9f9).

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers. Use the following nesting logic to create depth:
1.  **Base Layer:** `surface` (#f9f9f9) - The infinite canvas.
2.  **Sectioning Layer:** `surface_container_low` (#f3f3f4) - For sidebars or utility panels.
3.  **Component Layer:** `surface_container_lowest` (#ffffff) - For cards or active input areas. This creates a "lifted" effect without shadows.
4.  **Emphasis Layer:** `surface_container_high` (#e8e8e8) - For hovered states or inactive secondary modules.

### The "Glass & Signature" Rule
For floating elements (modals, dropdowns), use **Glassmorphism**. Apply `surface_container_lowest` at 80% opacity with a `24px` backdrop blur. This ensures the interface feels "digital-first" and integrated rather than "pasted on."

---

## 3. Typography
We use **Inter** as our sole typeface. Its geometric precision supports the architectural feel.

*   **Display Scale (`display-lg` to `display-sm`):** Reserved for high-impact moments or editorial headers. Use `primary` (#000000) with a letter-spacing of `-0.02em` to feel "tight" and authoritative.
*   **Headline & Title:** Use `primary` (#000000) for high contrast against the `surface`. 
*   **Body & Labels:** Use `on_surface_variant` (#474747) for long-form text. This slight reduction in contrast prevents eye strain and feels more sophisticated than "pure black."
*   **The Hierarchy Rule:** Never use font weight to solve a problem that can be solved by scale or color shift. High-end design breathes through the use of `label-md` in all-caps for metadata, contrasted against a `title-lg` header.

---

## 4. Elevation & Depth
In this system, elevation is a property of light and material, not "dropshadow.css."

*   **The Layering Principle:** Depth is achieved by "stacking." A card (`surface_container_lowest`) sitting on a section (`surface_container_low`) creates a soft, natural lift.
*   **Ambient Shadows:** For high-elevation elements like Modals, use a "Shadow-Glow."
    *   *Spec:* `0px 20px 40px rgba(26, 28, 28, 0.04)`. The shadow must be a tinted version of `on_surface` at a very low opacity.
*   **The "Ghost Border" Fallback:** If a border is required for accessibility (e.g., in high-contrast modes), use `outline_variant` (#c6c6c6) at **20% opacity**. 100% opaque borders are strictly forbidden as they "trap" the eye.

---

## 5. Components

### Buttons
*   **Primary:** Background `primary` (#000000), Text `on_primary` (#e2e2e2). Corner radius: `md` (0.375rem). No shadow.
*   **Secondary:** Background `surface_container_highest` (#e2e2e2), Text `on_surface` (#1a1c1c).
*   **Tertiary (Ghost):** No background. Text `on_surface`. Underline on hover only.

### Cards & Lists
*   **Prohibition:** No divider lines. Use vertical white space (`spacing-6` or `spacing-8`) to separate list items. 
*   **Hover State:** Shift background from `surface` to `surface_container_low`.

### Input Fields
*   **Default:** `surface_container_lowest` (#ffffff) with a 1px "Ghost Border" (`outline_variant` at 20%).
*   **Focus:** Keep the `surface_container_lowest` field surface and the 1px Ghost Border in `outline_variant` at 20% for structure, then add a 2px outline in `primary` (#000000) at 72% opacity with a 2px offset and a soft outer glow. Transition should be 200ms ease-in-out.

### Floating Command Bar (Signature Component)
Following a conversation-first assistant aesthetic, use a centered, floating input bar. 
*   **Style:** `surface_container_lowest` (90% opacity), backdrop-blur `12px`, `md` corner radius, and an ambient shadow.

---

## 6. Do's and Don'ts

### Do
*   **Do** use asymmetrical margins (e.g., a wider left margin for text columns) to create an editorial, non-templated feel.
*   **Do** use generous section spacing in the `5.5rem` to `7rem` range between major sections. Generous whitespace is a luxury signifier.
*   **Do** use `ROUND_SIX` (`md`: 0.375rem) consistently. It is the "golden mean" between a harsh square and a playful circle.

### Don't
*   **Don't** use pure black (#000000) for body text; use `on_surface_variant` (#474747) to maintain a soft, premium "ink-on-paper" look.
*   **Don't** use icons as primary navigation. Use `label-md` typography to emphasize textual clarity.
*   **Don't** use "Card-in-Card" layouts. If you need a sub-section, use a background color shift or a change in typography weight, never an additional bordered container.
