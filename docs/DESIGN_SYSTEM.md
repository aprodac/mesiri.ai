> **Superseded for the web dashboard by [DESIGN.md](DESIGN.md) (24 Oct 2026, WEB-19).** Kept for history; it does not describe the shipped product.

# Mesiri.ai — Complete UI Design System

> **Version:** 1.0
> **Platforms:** Web Dashboard + Mobile Application
> **Design Direction:** Swiss Minimal × Modern SaaS × Operational Software
> **Core Philosophy:** Light interfaces for everyday work. Dark components for high-emphasis intelligence. Color for meaning, not decoration.

---

## 1. UI Technology Stack

Do **not** add more UI libraries unless there is a concrete technical requirement. Too many UI libraries will create inconsistent spacing, icons, interactions, and component APIs.

| Purpose              | Web                          | Mobile                        |
| -------------------- | ---------------------------- | ----------------------------- |
| Framework            | React / Next.js              | React Native + Expo           |
| UI Primitives        | Radix UI                     | React Native primitives       |
| Component Foundation | shadcn/ui source code        | Custom Mesiri components      |
| Styling              | Tailwind CSS + CSS Variables | StyleSheet + Design Tokens    |
| Icons                | Lucide                       | Lucide React Native           |
| Forms                | React Hook Form              | React Hook Form               |
| Validation           | Zod                          | Zod                           |
| Charts               | Recharts                     | Victory Native                |
| Animation            | Motion                       | Reanimated                    |
| Bottom Sheets        | Radix Dialog / Drawer        | Gorhom Bottom Sheet           |
| Toasts               | Sonner                       | Custom Toast / Toast library  |
| Tables               | TanStack Table               | Custom Lists / FlashList      |
| Virtualized Lists    | TanStack Virtual             | FlashList                     |
| Dates                | date-fns                     | date-fns                      |
| Command Menu         | cmdk                         | Custom Search / Command Sheet |
| Drag & Drop          | dnd-kit                      | Gesture Handler + Reanimated  |
| Server State         | TanStack Query               | TanStack Query                |
| Complex Client State | Zustand                      | Zustand                       |

### Recommended Additional Libraries

**shadcn/ui** is useful for Mesiri because components are copied into your codebase rather than treated as an external visual system. Use it as a component foundation, then rewrite the styling using Mesiri tokens.

**TanStack Table** should power complex operational tables: bills, expenses, projects, users, activities, procurement records, and reports.

**TanStack Query** should be the standard server-state layer.

**FlashList** should be considered for large mobile timelines, activity feeds, message history, and project lists.

**Sonner** is suitable for lightweight web toast notifications.

**cmdk** is useful if Mesiri introduces a global command/search interface.

Do not use Material UI, Ant Design, Bootstrap, Chakra UI, Mantine, and shadcn/ui simultaneously.

The recommended architecture is:

```text
Radix UI
   +
shadcn/ui Source Components
   +
Mesiri Design Tokens
   ↓
Mesiri Component Library
   ↓
Mesiri Applications
```

---

# 2. Design Principles

## 2.1 Clarity First

Information must be understandable within seconds.

Prefer:

```text
Clear hierarchy
→ Strong labels
→ Important values
→ Status
→ Action
```

Avoid excessive decoration, nested cards, redundant labels, and unnecessary dashboards.

---

## 2.2 Operational Density

Mesiri is operational software.

The interface should display enough information for users to make decisions without becoming visually crowded.

Use progressive disclosure:

```text
Summary
↓
Important Status
↓
Details
↓
Evidence
↓
History
```

---

## 2.3 Intelligence Has Hierarchy

AI insights, project health, financial summaries, anomalies, and critical analytics deserve stronger visual emphasis.

This is where the **Dark Component System** is used.

---

## 2.4 Consistency Creates Trust

Every:

```text
Button
Input
Card
Status
Table
Modal
Chart
Navigation item
Empty state
Loading state
```

must come from the Mesiri component system.

---

# 3. Color System

## 3.1 Brand Colors

```css
--primary: #7ED957;
--primary-hover: #6FCB48;
--primary-active: #5EB83A;

--primary-soft: #EFFBE8;
--primary-subtle: #F6FDEF;

--dark: #1F222B;
--dark-deep: #0E1116;

--info-soft: #BEE6FF;
--warning-soft: #FFD166;
--accent-soft: #CDB4FF;
```

---

## 3.2 Semantic Colors

```css
--success: #22C55E;
--success-soft: #DCFCE7;

--error: #EF4444;
--error-soft: #FEE2E2;

--warning: #F59E0B;
--warning-soft: #FEF3C7;

--info: #3B82F6;
--info-soft: #DBEAFE;
```

---

## 3.3 Neutral Scale

```css
--neutral-950: #080A0D;
--neutral-900: #0E1116;
--neutral-800: #1F222B;
--neutral-700: #2C3341;
--neutral-600: #485563;
--neutral-500: #687280;
--neutral-400: #9CA3AF;
--neutral-300: #D1D5DB;
--neutral-200: #E5E7EB;
--neutral-100: #F3F4F6;
--neutral-50: #FAFAFB;
--white: #FFFFFF;
```

---

# 4. Surface System

Mesiri uses four primary surface levels.

```text
APPLICATION
#FAFAFB

    ↓

STANDARD SURFACE
#FFFFFF

    ↓

SUBTLE SURFACE
#F3F4F6

    ↓

DARK EMPHASIS SURFACE
#0E1116 / #1F222B
```

## Surface Tokens

```css
--surface-app: #FAFAFB;

--surface-primary: #FFFFFF;

--surface-secondary: #F3F4F6;

--surface-dark: #0E1116;

--surface-dark-elevated: #1F222B;
```

Avoid creating a separate card background for every section.

Whitespace is the default separation mechanism.

---

# 5. Dark Component System

The Dark Component is a defining visual pattern of Mesiri.

It is **not Dark Mode**.

It is an intentionally rare, high-emphasis component.

## Use For

```text
Project Health

Project Progress

AI Insights

Financial Overview

Critical Alerts

Operational Intelligence

Anomaly Detection

Executive Summaries

Important Charts
```

## Do Not Use For

```text
Forms

Settings

Basic CRUD screens

Standard tables

Every chart

Every dashboard section

Decorative banners
```

## Dark Component Tokens

```css
--dark-component-bg: #0E1116;

--dark-component-elevated: #1F222B;

--dark-component-border:
rgba(255,255,255,0.10);

--dark-component-text: #FFFFFF;

--dark-component-text-secondary:
#D1D5DB;

--dark-component-text-muted:
#9CA3AF;

--dark-component-primary:
#A3F23D;
```

## Structure

```text
┌────────────────────────────────────────┐
│ TITLE                         CONTROL  │
│ Supporting context                      │
│                                        │
│             VISUALIZATION              │
│                                        │
│ ● STATUS                      VALUE    │
│ ● STATUS                      VALUE    │
│ ● STATUS                      VALUE    │
│                                        │
│ ┌────────────────────────────────────┐ │
│ │ PRIMARY ACTION                     │ │
│ └────────────────────────────────────┘ │
└────────────────────────────────────────┘
```

## Frequency

```text
Mobile Screen:
0–1 dark components

Desktop Dashboard:
1 primary dark component

Complex Analytics Dashboard:
Maximum 2
```

---

# 6. Typography

## Font

```text
Inter
```

Fallback:

```css
font-family:
Inter,
-apple-system,
BlinkMacSystemFont,
"Segoe UI",
sans-serif;
```

## Scale

| Token          | Size | Line Height | Weight |
| -------------- | ---: | ----------: | -----: |
| Display XL     | 40px |        48px |    600 |
| Display        | 32px |        40px |    600 |
| H1             | 24px |        32px |    600 |
| H2             | 20px |        28px |    600 |
| H3             | 16px |        24px |    600 |
| Body Large     | 16px |        24px |    400 |
| Body           | 14px |        20px |    400 |
| Body Medium    | 14px |        20px |    500 |
| Caption        | 12px |        16px |    400 |
| Caption Medium | 12px |        16px |    500 |
| Micro          | 11px |        14px |    500 |

Use `600` as the maximum standard heading weight.

Avoid excessive `700–900` weights.

---

# 7. Spacing System

Base unit:

```text
4px
```

Tokens:

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
--space-16: 64px;
```

## Layout Usage

```text
Icon ↔ Text
8px

Label ↔ Input
8px

Title ↔ Supporting Text
4–8px

Component Internal Gap
12–16px

Card Padding
16–24px

Section Gap
24–32px

Desktop Page Padding
24–40px

Mobile Page Padding
16–20px
```

---

# 8. Border Radius

```css
--radius-xs: 4px;
--radius-sm: 8px;
--radius-md: 12px;
--radius-lg: 16px;
--radius-xl: 20px;
--radius-2xl: 24px;
--radius-full: 9999px;
```

Defaults:

```text
Input       10–12px

Button      10–12px

Card        16px

Dark Panel  16–20px

Modal       20px

Bottom Sheet
24px top corners
```

---

# 9. Border System

```css
--border-subtle: #F3F4F6;

--border-default: #E5E7EB;

--border-strong: #D1D5DB;

--border-focus: #7ED957;

--border-dark:
rgba(255,255,255,0.10);
```

Default:

```text
1px solid
```

Avoid using thick borders to establish hierarchy.

---

# 10. Elevation System

```css
--shadow-0:
none;

--shadow-1:
0 1px 2px rgba(16,24,40,0.05);

--shadow-2:
0 2px 4px rgba(16,24,40,0.06);

--shadow-3:
0 4px 12px rgba(16,24,40,0.08);

--shadow-4:
0 8px 24px rgba(16,24,40,0.10);

--shadow-overlay:
0 20px 48px rgba(16,24,40,0.18);
```

Hierarchy priority:

```text
Whitespace
↓
Typography
↓
Surface Contrast
↓
Border
↓
Shadow
```

---

# 11. Icon System

## Library

```text
Lucide
```

Use:

```text
lucide-react

lucide-react-native
```

## Rules

```text
Style:
Outline

Stroke:
2px

Line Caps:
Rounded

Line Joins:
Rounded
```

Sizes:

```text
14px Micro

16px Dense

20px Standard

24px Navigation

32px Feature

40px Empty State
```

Never mix Lucide with Font Awesome, Material Icons, Heroicons, Phosphor, and random SVG icon sets.

Custom icons are allowed only for Mesiri-specific domain concepts.

---

# 12. Button System

## Sizes

```text
Small
32px

Medium
40px

Large
48px
```

Minimum mobile touch target:

```text
44 × 44px
```

## Primary

```css
background: #7ED957;
color: #0E1116;
```

## Secondary

```css
background: #FFFFFF;
color: #1F222B;
border: 1px solid #D1D5DB;
```

## Tertiary

```css
background: transparent;
color: #1F222B;
```

## Destructive

```css
background: #EF4444;
color: #FFFFFF;
```

## Dark Component CTA

```css
background: #A3F23D;
color: #0E1116;
```

Every button must support:

```text
Default

Hover

Pressed

Focus

Loading

Disabled
```

---

# 13. Input System

Supported inputs:

```text
Text Input

Textarea

Number Input

Search

Select

Combobox

Date Picker

Date Range

Checkbox

Radio

Switch

File Upload

OTP Input
```

Default:

```text
Height:
44px

Radius:
12px

Background:
#FFFFFF

Border:
#D1D5DB

Text:
#1F222B

Placeholder:
#9CA3AF
```

Focus:

```text
Border:
#7ED957

Focus Ring:
0 0 0 3px rgba(126,217,87,0.20)
```

Error:

```text
Border:
#EF4444

Helper Text:
#EF4444
```

---

# 14. Card System

## Standard Card

```text
White Surface
1px Border
16px Radius
16–24px Padding
Shadow 0–1
```

## KPI Card

```text
Icon

Label

Primary Value

Trend

Optional Context
```

## Project Card

```text
Image / Thumbnail

Project Name

Project Type

Status

Progress

Optional Metadata
```

## Activity Item

```text
Semantic Icon

Primary Activity

Secondary Context

Timestamp
```

## Insight Card

```text
AI / Intelligence Label

Insight

Supporting Evidence

Confidence / Importance

Recommended Action
```

---

# 15. Status System

Every status must have:

```text
Icon or Dot

Label

Color

Optional Supporting Text
```

Example:

| Status     | Color                                   |
| ---------- | --------------------------------------- |
| On Track   | Primary Green                           |
| Completed  | Success                                 |
| At Risk    | Warning                                 |
| Delayed    | Soft Blue / Error depending on severity |
| Blocked    | Error                                   |
| Pending    | Neutral                                 |
| Draft      | Neutral                                 |
| Processing | Info                                    |

Never communicate status through color alone.

---

# 16. Badge System

Variants:

```text
Neutral

Primary

Success

Warning

Error

Info

Purple
```

Sizes:

```text
Small
20px height

Medium
24px height
```

Badges should not become buttons.

---

# 17. Avatar System

Sizes:

```text
24px

32px

40px

48px

64px
```

Fallback:

```text
User Image
↓
Initials
↓
Generic User Icon
```

Avatar groups should show maximum 3–4 visible avatars followed by:

```text
+5
```

---

# 18. Table System

Use TanStack Table.

Structure:

```text
Table Toolbar

Search

Filters

View Options

Bulk Actions

Column Headers

Rows

Pagination
```

Row heights:

```text
Compact:
40px

Default:
48px

Comfortable:
56px
```

Tables must support:

```text
Loading

Empty

Error

Sorting

Filtering

Pagination

Column Visibility

Row Selection

Bulk Actions
```

Avoid putting every row inside a separate card on desktop.

---

# 19. Mobile List System

Mobile operational screens should prefer lists over desktop-style tables.

Structure:

```text
Primary Label

Status

Important Value

Secondary Metadata

Chevron / Action
```

Row height:

```text
Minimum 56px

Recommended 64–72px
```

Use FlashList when datasets can become large.

---

# 20. Navigation System

## Desktop

```text
App Shell

Sidebar

Top Header

Main Content
```

Sidebar:

```text
Collapsed:
64–72px

Expanded:
240–280px
```

Use:

```text
Icon

Label

Active Indicator

Optional Badge
```

## Mobile

Top navigation:

```text
Logo / Page Title

Search

Notifications

Avatar
```

Bottom navigation:

```text
Maximum 5 Items
```

Recommended:

```text
Dashboard

Projects

Primary Action

Site

Reports
```

---

# 21. Modal System

Use for focused tasks.

```text
Header

Title

Optional Description

Content

Footer Actions
```

Widths:

```text
Small:
400px

Medium:
560px

Large:
720px

XL:
960px
```

Do not use modals for complex multi-step operational workflows.

Use full pages or drawers.

---

# 22. Drawer / Sheet System

Use for:

```text
Filters

Record Details

Quick Edit

Supporting Information

Mobile Actions
```

Desktop width:

```text
400–560px
```

Mobile:

```text
Bottom Sheet
```

---

# 23. Toast System

Use Sonner on web.

Types:

```text
Success

Error

Warning

Info

Loading
```

Toasts should communicate temporary system feedback.

Do not use toasts for critical information that users must remember.

---

# 24. Tooltip System

Use tooltips for:

```text
Unlabeled Icon Buttons

Truncated Information

Short Explanations

Chart Values
```

Do not hide critical information inside tooltips.

---

# 25. Dropdown / Menu System

Structure:

```text
Optional Label

Menu Item

Menu Item

Divider

Destructive Action
```

Minimum row height:

```text
36–40px
```

Destructive actions should remain visually separated.

---

# 26. Tabs System

Use tabs only when sections are closely related.

```text
Overview

Activity

Documents

Financials
```

Avoid more than:

```text
5–6 visible tabs
```

On mobile, use horizontally scrollable tabs when necessary.

---

# 27. Search System

Mesiri should have three levels of search.

```text
Local Search

Page / Module Search

Global Search / Command Menu
```

Global search can use:

```text
cmdk
```

Search results should be grouped by entity:

```text
Projects

People

Documents

Activities

Bills

Reports
```

---

# 28. Filter System

Desktop:

```text
Inline Filters

Popover Filters

Filter Drawer for Complex Cases
```

Mobile:

```text
Filter Bottom Sheet
```

Always show active filter count.

```text
Filters (3)
```

Provide:

```text
Clear All
```

---

# 29. Date System

Use:

```text
date-fns
```

Display:

```text
Today

Yesterday

2h ago

5 Jul 2026

5 Jul 2026, 10:30 AM
```

Use relative dates for recent activity.

Use absolute dates for financial, legal, and historical records.

---

# 30. Chart System

Web:

```text
Recharts
```

Mobile:

```text
Victory Native
```

Create Mesiri wrappers:

```text
MesiriDonutChart

MesiriBarChart

MesiriLineChart

MesiriAreaChart

MesiriTrendChart

MesiriProgressChart
```

Charts must support:

```text
Title

Context

Legend

Tooltip

Empty State

Loading State

Error State
```

Maximum recommended categories:

```text
5
```

---

# 31. Data Visualization Colors

```css
--chart-primary: #7ED957;

--chart-primary-bright: #A3F23D;

--chart-warning: #FFD166;

--chart-blue: #9FB4FF;

--chart-purple: #CDB4FF;

--chart-neutral: #687280;

--chart-error: #EF4444;
```

Charts should never generate random colors.

---

# 32. Loading System

## Button Loading

```text
Spinner + Existing Label
```

## Content Loading

Use skeletons matching the final content structure.

## Page Loading

```text
Page Shell remains visible

Content Skeleton appears
```

Avoid full-screen spinners for normal navigation.

---

# 33. Empty State System

Structure:

```text
Icon / Minimal Illustration

Clear Title

Explanation

Primary Action

Optional Secondary Action
```

Example:

```text
No projects yet

Create your first project to start
tracking site activity and progress.

[ Create Project ]
```

---

# 34. Error State System

Structure:

```text
Error Indicator

Clear Explanation

Recovery Action

Optional Technical Details
```

Never show raw backend errors directly to users.

---

# 35. Skeleton System

Use skeletons for:

```text
Dashboard Cards

Tables

Lists

Charts

Project Cards

Profile Data
```

Animation should be subtle.

Avoid excessive shimmer effects.

---

# 36. Motion System

Web:

```text
Motion
```

Mobile:

```text
Reanimated
```

Durations:

```text
Fast:
120ms

Default:
180ms

Moderate:
240ms

Slow:
320ms
```

Easing:

```css
--ease-standard:
cubic-bezier(0.2, 0, 0, 1);

--ease-enter:
cubic-bezier(0, 0, 0, 1);

--ease-exit:
cubic-bezier(0.3, 0, 1, 1);
```

Use motion for:

```text
State Changes

Navigation

Expandable Content

Bottom Sheets

Modal Entry

Progress Updates

Feedback
```

Do not animate every card on page load.

---

# 37. Responsive Breakpoints

```css
--breakpoint-sm: 640px;

--breakpoint-md: 768px;

--breakpoint-lg: 1024px;

--breakpoint-xl: 1280px;

--breakpoint-2xl: 1536px;
```

Design mobile-first.

Do not simply shrink desktop dashboards into mobile screens.

---

# 38. Page Width System

```text
Standard Application:
1280px

Wide Dashboard:
1440px

Analytics:
1600px

Reading / Forms:
720–960px
```

Not every page should use the full available width.

---

# 39. Grid System

Desktop:

```text
12 Columns

24px Gutters
```

Tablet:

```text
8 Columns

20px Gutters
```

Mobile:

```text
4 Columns

16px Gutters
```

---

# 40. Accessibility

Requirements:

```text
Normal Text:
4.5:1 Contrast

Large Text:
3:1 Contrast

Touch Targets:
44×44px Minimum

Keyboard Navigation:
Required

Visible Focus:
Required

Reduced Motion:
Supported

Screen Reader Labels:
Required

Status:
Never Color Only
```

---

# 41. Mesiri Component Library

Create:

```text
packages/ui

packages/tokens

packages/icons

packages/charts
```

## Core Components

```text
MesiriButton

MesiriIconButton

MesiriInput

MesiriTextarea

MesiriSelect

MesiriCombobox

MesiriCheckbox

MesiriRadio

MesiriSwitch

MesiriDatePicker

MesiriBadge

MesiriStatus

MesiriAvatar

MesiriCard

MesiriKpiCard

MesiriProjectCard

MesiriActivityItem

MesiriInsightCard

MesiriDarkPanel

MesiriTable

MesiriDataList

MesiriTabs

MesiriModal

MesiriDrawer

MesiriBottomSheet

MesiriDropdown

MesiriTooltip

MesiriToast

MesiriSkeleton

MesiriEmptyState

MesiriErrorState

MesiriPagination

MesiriSearch

MesiriFilterBar

MesiriPageHeader

MesiriSectionHeader

MesiriDonutChart

MesiriBarChart

MesiriLineChart

MesiriProgress
```

---

# 42. Import Rule

Feature code should **not directly import third-party UI libraries**.

Avoid:

```ts
import { Button } from "@radix-ui/...";
import { BarChart } from "recharts";
import { Search } from "lucide-react";
```

Prefer:

```ts
import {
  MesiriButton,
  MesiriIcon,
  MesiriBarChart,
} from "@mesiri/ui";
```

Exception:

```text
packages/ui

packages/charts

packages/icons
```

may import third-party UI libraries.

---

# 43. Component API Rule

Components should expose semantic APIs.

Avoid:

```tsx
<Card
  bg="#0E1116"
  radius={18}
  padding={22}
  textColor="#FFFFFF"
/>
```

Prefer:

```tsx
<MesiriDarkPanel
  title="Project Progress"
  action={<ProjectFilter />}
>
  <ProjectProgressChart />
</MesiriDarkPanel>
```

The design system should own visual decisions.

Feature developers should provide content and behavior.

---

# 44. Final Library Decision

For Mesiri, I would lock the stack to:

```text
WEB

Radix UI
shadcn/ui
Tailwind CSS
Lucide
Recharts
Motion
React Hook Form
Zod
TanStack Query
TanStack Table
TanStack Virtual
Zustand
Sonner
cmdk
dnd-kit
date-fns


MOBILE

React Native + Expo
Lucide React Native
React Native Reanimated
React Native Gesture Handler
Gorhom Bottom Sheet
Victory Native
React Hook Form
Zod
TanStack Query
Zustand
FlashList
date-fns
```

The key architecture decision is this:

```text
THIRD-PARTY LIBRARIES
          ↓
MESIRI DESIGN TOKENS
          ↓
MESIRI UI COMPONENTS
          ↓
PRODUCT FEATURES
```

**Do not build Mesiri directly on top of shadcn/ui screens or random component libraries.** Use Radix and shadcn as implementation foundations, then create a thin Mesiri component layer.

That matters because Mesiri is likely to have multiple interfaces over time: **mobile app, owner dashboard, admin console, ERP modules, and potentially customer-facing portals**. A controlled component system now will reduce redesign and inconsistency later.
