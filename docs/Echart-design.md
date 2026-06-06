# ECharts 数据与流程可视化看板设计

## 项目现状

- **前端**: Next.js 14 + React 18 + TypeScript + Tailwind CSS
- **图表库**: 无（零依赖，完全空白）
- **数据**: 每次竞品分析报告产出丰富的结构化数据（`CompetitorAnalysisState`），包含 evidence、claims、reviews、competitor knowledge 等，但全部以纯文本/Markdown 渲染
- **现有"看板"**: `LogsSection.tsx` 仅有 4 个静态数字卡片 + 7 阶段时间线文本列表

## 推荐方案：`echarts-for-react`

```
npm install echarts echarts-for-react
```

- 与 React 18 + TypeScript 声明式使用，学习成本低
- ECharts 按需引入，treeshaking 友好
- 主题色与 tailwind.config.ts 的 teal accent 统一

---

## 第一优先：替换现有静态卡片

### 1. 证据来源分布 — 堆叠条形图

**数据来源**: `evidence_index[]` → `source_type`, `competitor`

**价值**: 20+ 种来源类型（official_site, docs, blog, news, review, marketplace, social 等）按竞品堆叠，横向对比谁的证据构成偏一手还是二手。

**Chart 类型**: 横向堆叠条形图（`series.type: "bar"` + `xAxis: { type: "value" }` + `yAxis: { type: "category", data: competitors }`）

```
         official_site  docs  blog  news  review  other
  ─────────────────────────────────────────────────────
  竞品A   ████████████  ████  ███   ██    ████    ██
  竞品B   ██████        █████ ████  ████  ██      ████
  竞品C   █████████████  ██    ██    █████ ██      ██
```

### 2. 声明验证状态 — 环形图

**数据来源**: `claim_support_reviews[]` → `support_status`

**价值**: supported / weak / contradicted / unverifiable 四类分布，一眼看出某个竞品的分析是否站得住脚。现在的 LogsSection 只看一个数字，看不出比例。

**Chart 类型**: 环形图（`series.type: "pie"` + `radius: ["40%", "70%"]`），支持按竞品 toggle。

```
       ┌──────────┐
      ╱  supported  ╲
     ╱     ██████    ╲
    │     ██  ██      │
    │    ██    ████   │
    │    ██  weak ██  │
     ╲    ████████   ╱
      ╲  contr·unv  ╱
       └──────────┘
```

### 3. 竞品 x 维度信心热力图

**数据来源**: `direction_results[]` → `direction_name`, `competitor`, `confidence`

**价值**: 竞品分析核心价值——各竞品在各维度的优劣一目了然。颜色深浅映射 confidence 高低。

**Chart 类型**: 热力图（`series.type: "heatmap"` + `visualMap`）

```
             维度A  维度B  维度C  维度D  维度E
  竞品A      ████   ██     █████  ██     ██
  竞品B      ██     █████  ███    █████  █████
  竞品C      █████  ███    ██     ███    █████
```

---

## 第二优先：流程可视化

### 4. Agent 流水线 — 漏斗图

**数据来源**: `trace_summary` → `agents[]`, 各阶段产出物计数

**价值**: 7 阶段 DAG（Planning → Collection → Knowledge Structuring → Analysis → Claim Review → Report Writing → Publishing），用漏斗展示 evidence 从收集到最终报告的递减过程，直观反映分析质量。

**Chart 类型**: 漏斗图（`series.type: "funnel"`）

```
  Planning         ████████████  ▏12 dimensions
  Collection       ██████████████████████████████  ▏83 evidence items
  Structuring      ██████████████████  ▏42 knowledge facts
  Analysis         ██████████████  ▏31 claims
  Claim Review     ██████████  ▏23 supported claims
  Report Writing   ██████  ▏1 report
  Publishing       ██  ▏4 artifacts
```

### 5. 研究分支覆盖 — 旭日图

**数据来源**: `research_branches[]`, `research_tasks[]`

**价值**: 展示一次分析中各竞品、各维度展开了多少搜索分支，每个分支的 evidence 产出量。层级关系：Research → Branch → Task → Evidence。

**Chart 类型**: 旭日图（`series.type: "sunburst"`）

```
         ┌──────────────────────┐
         │     Research Run     │
         │  ┌──────┐ ┌──────┐  │
         │  │竞品A │ │竞品B │  │
         │  │▓▓▓▓▓│ │▓▓▓▓▓│  │
         │  │▓定价▓│ │▓功能▓│  │
         │  └──────┘ └──────┘  │
         └──────────────────────┘
```

---

## 第三优先：交互式探索

### 6. 竞品能力雷达图

**数据来源**: `competitor_knowledge[]` → `feature_tree`, `pricing_model`, `user_personas`

**价值**: 将功能覆盖、定价竞争力、用户适配度、证据置信度等关键维度综合成雷达图，支持 2-5 个竞品叠加对比。

**Chart 类型**: 雷达图（`series.type: "radar"`），多 series 叠加

```
           功能覆盖
              /\
             /  \
    用户适配 /    \ 定价竞争力
           /  ⬤   \
          /    ⬤    \
         /     ⬤     \
        /──────⬤──────\
       / 证据置信度     \
      /                  \
      \    市场覆盖     /
       \              /
        \    声量    /
         \         /
          ────────
```

### 7. 证据-声明流向 — 桑基图

**数据来源**: `evidence_items[]` + `analysis_claims[]` + `claim_support_reviews[]`

**价值**: 展示 evidence → claim → review 的流向关系，按 `support_status` 着色，直观看到哪些 evidence 支撑了哪些声明，哪些被判定为矛盾。

**Chart 类型**: 桑基图（`series.type: "sankey"`）

```
  evidence_1 ──────────────┐
  evidence_2 ───────────┐  │
  evidence_3 ──────┐    │  │
                    ▼    ▼  ▼
                    claim_A ──── supported
                    claim_B ──── weak ──── re-collection
                    claim_C ──── contradicted
```

---

## 实施路线

### Phase 1 — 改造 LogsSection（1-2 天）

将 `frontend/nextjs/components/ResearchBlocks/LogsSection.tsx` 中 4 个静态数字卡片替换为：

- 证据来源分布堆叠条形图
- 声明验证状态环形图
- 竞品 x 维度热力图
- 保留原有的 Needs Review 列表，挂在图下方

数据从 `reportContext` 中取：`state.evidence_items`, `state.claim_support_reviews`, `state.direction_results`。

### Phase 2 — 新建 Dashboard 页面（2-3 天）

新建 `frontend/nextjs/app/dashboard/[id]/page.tsx`，独立的全屏看板页面：

- 左侧：漏斗图 + 旭日图（流程视角）
- 右侧：雷达图 + 桑基图（结果视角）
- 顶部：热力图（总览视角）

从 `/api/reports/{id}` 获取完整报告数据。

### Phase 3 — 交互增强（1-2 天）

- 图表联动：点击热力图某格 → 下方桑基图/雷达图过滤到该维度
- 竞品 toggle：通过 legend 切换竞品对比
- 时间维度：多轮分析的趋势对比（需要后端提供多次 run 的数据）

---

## 依赖

```json
{
  "echarts": "^5.5.0",
  "echarts-for-react": "^3.0.2"
}
```

ECharts 按需引入以减少包体积：

```typescript
import * as echarts from "echarts/core";
import { BarChart, PieChart, HeatmapChart, FunnelChart, RadarChart, SankeyChart, SunburstChart } from "echarts/charts";
import { TitleComponent, TooltipComponent, LegendComponent, VisualMapComponent, GridComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart, PieChart, HeatmapChart, FunnelChart, RadarChart, SankeyChart, SunburstChart,
  TitleComponent, TooltipComponent, LegendComponent, VisualMapComponent, GridComponent,
  CanvasRenderer,
]);
```

## 配色方案

与 tailwind.config.ts 的 teal accent 统一：

```typescript
const CHART_COLORS = {
  teal:     "#0d9488",  // teal-600
  tealDark: "#0f766e",  // teal-700
  tealLight:"#5eead4",  // teal-300
  amber:    "#f59e0b",  // amber-500
  red:      "#ef4444",  // red-500
  blue:     "#3b82f6",  // blue-500
  purple:   "#8b5cf6",  // violet-500
  green:    "#22c55e",  // green-500
};
```
