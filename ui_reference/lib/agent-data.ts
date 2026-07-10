export type NavId =
  | "dashboard"
  | "agent"
  | "topics"
  | "pipeline"
  | "analytics"
  | "settings"

export const examplePrompts = [
  '分析书籍《置身事内》',
  "从这本书生成视频选题",
  "我应该先做哪个选题？",
  "分析我最近的视频表现",
]

export const reasoningSteps = [
  { label: "正在解析书籍结构与核心论点…", detail: "已识别 9 个章节 · 142 个关键观点" },
  { label: "提炼可传播的关键洞察…", detail: "筛选出 5 个高记忆点的金句" },
  { label: "评估爆款潜力与受众匹配度…", detail: "结合近 30 天平台热度建模" },
  { label: "生成候选选题…", detail: "产出 5 个差异化选题角度" },
  { label: "推荐下一步行动…", detail: "建议优先制作「地方政府的钱从哪来」" },
]

export type Topic = {
  id: string
  title: string
  viralScore: number
  reason: string
  audience: string
  angle: string
}

export const topics: Topic[] = [
  {
    id: "t1",
    title: "你交的税，到底去了哪里？",
    viralScore: 92,
    reason: "强代入感的钱包话题，天然引发评论区追问",
    audience: "20-35 岁职场新人",
    angle: "用一笔工资单拆解财政流向",
  },
  {
    id: "t2",
    title: "地方政府的钱，其实是借来的？",
    viralScore: 88,
    reason: "认知反差强，适合做 3 秒强钩子开场",
    audience: "关注经济与房产的人群",
    angle: "土地财政的因果链可视化讲解",
  },
  {
    id: "t3",
    title: "为什么有的城市越修路越穷？",
    viralScore: 81,
    reason: "贴近生活观察，地域话题易触发转发",
    audience: "二三线城市观众",
    angle: "基建投资回报的反直觉案例",
  },
  {
    id: "t4",
    title: "GDP 增长了，为什么我没感觉？",
    viralScore: 79,
    reason: "情绪共鸣点明确，标题自带争议性",
    audience: "泛大众 / 财经入门",
    angle: "宏观数据与个人体感的落差",
  },
  {
    id: "t5",
    title: "一个县城的财政，能撑多久？",
    viralScore: 74,
    reason: "故事性强，适合做系列化连载内容",
    audience: "深度内容偏好用户",
    angle: "以单个县城为样本的微观叙事",
  },
]

export const script = {
  title: "你交的税，到底去了哪里？",
  wordCount: 486,
  insight: "财政是理解国家运转的底层操作系统",
  strategy: "钩子 → 反差 → 拆解 → 升华 的四段式结构",
}

export type PipelineStep = {
  name: string
  status: "done" | "active" | "pending"
}

export const pipeline: PipelineStep[] = [
  { name: "脚本", status: "done" },
  { name: "内容单元", status: "done" },
  { name: "视觉节拍", status: "done" },
  { name: "图像提示词", status: "active" },
  { name: "图像生成", status: "pending" },
  { name: "语音生成", status: "pending" },
  { name: "时间轴", status: "pending" },
  { name: "字幕", status: "pending" },
  { name: "成片", status: "pending" },
]

export const analytics = {
  totalVideos: 48,
  avgViews: "32.6万",
  trend: [12, 18, 15, 24, 22, 31, 28, 38, 35, 44, 41, 52],
  topTopics: [
    { title: "你交的税，到底去了哪里？", views: "128.4万" },
    { title: "地方政府的钱是借来的？", views: "96.1万" },
    { title: "GDP 增长了我没感觉", views: "71.8万" },
  ],
  recommendations: [
    "「财政科普」赛道完播率高出大盘 23%，建议加大产出",
    "周四晚 8 点发布的视频平均互动率最高",
    "把核心金句放在前 3 秒可提升 14% 的留存",
  ],
}
