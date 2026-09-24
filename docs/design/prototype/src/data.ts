export type Work = {
  id: string
  title: string
  summary: string
  status: string
  owner: string
  date: string
  tag: string
}
export const initialWork: Work[] = [
  {
    id: 'WK-024',
    title: '协调官网上线前的内容验收',
    summary: '完成首页与产品页的文案核对，和设计同事确认最后一轮调整。',
    status: '进行中',
    owner: '林悦',
    date: '今天',
    tag: '官网上线',
  },
  {
    id: 'WK-023',
    title: '确认客户试用反馈与下一步安排',
    summary: '整理首批客户的试用反馈，将问题归类并同步给产品团队。',
    status: '待处理',
    owner: '陈一',
    date: '明天',
    tag: '客户体验',
  },
  {
    id: 'WK-022',
    title: '跟进支付接口联调',
    summary: '等待合作方提供测试账号，已完成内部接口检查。',
    status: '有阻碍',
    owner: '许言',
    date: '今天',
    tag: '产品迭代',
  },
  {
    id: 'WK-021',
    title: '整理本周产品评审结论',
    summary: '补齐负责人和交付节点，形成可跟进的行动清单。',
    status: '进行中',
    owner: '林悦',
    date: '9月25日',
    tag: '产品迭代',
  },
  {
    id: 'WK-020',
    title: '准备客户回访问题清单',
    summary: '结合上周的反馈，明确本次回访要验证的三个问题。',
    status: '已完成',
    owner: '周可',
    date: '9月22日',
    tag: '客户体验',
  },
  {
    id: 'WK-019',
    title: '同步第三季度项目资料',
    summary: '整理需求文档与项目总结，完成团队资料归档。',
    status: '已完成',
    owner: '陈一',
    date: '9月21日',
    tag: '团队协作',
  },
]
export const nav = [
  { id: 'assistant', label: '工作助手', icon: 'Sparkles' },
  { id: 'work', label: '我的工作', icon: 'CircleCheck' },
  { id: 'team', label: '团队看板', icon: 'PanelsTopLeft' },
  { id: 'reports', label: '我的报告', icon: 'Files' },
]
export const statuses = ['全部状态', '待处理', '进行中', '有阻碍', '已完成']
