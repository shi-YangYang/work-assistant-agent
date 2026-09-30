import {
  AudioLines,
  BriefcaseBusiness,
  CalendarClock,
  ChartColumn,
  Cpu,
  FileText,
  LayoutDashboard,
  LifeBuoy,
  MessageSquare,
  Palette,
  UserRound,
  Users,
} from 'lucide-react'

export const pages = [
  {
    path: '/assistant',
    title: '工作助手',
    detail: '继续对话，记录进展与查询资料',
    icon: MessageSquare,
  },
  {
    path: '/work',
    title: '我的工作',
    detail: '查找工作事项，更新进展与下一步',
    icon: BriefcaseBusiness,
  },
  { path: '/reports', title: '我的报告', detail: '查看、编辑和提交日报与周报', icon: FileText },
  {
    path: '/team',
    title: '团队看板',
    detail: '了解员工进展、阻碍与汇报情况',
    icon: LayoutDashboard,
    admin: true,
  },
  {
    path: '/members',
    title: '成员管理',
    detail: '管理员工账号与访问权限',
    icon: Users,
    admin: true,
  },
]

export const settingsPages = [
  {
    path: '/settings/voiceprints',
    title: '公司声纹',
    detail: '登记成员声音，供桌面会议识别发言者',
    icon: AudioLines,
    admin: true,
  },
  {
    path: '/settings/support',
    title: '问题反馈',
    detail: '描述使用问题，查看管理员处理结果',
    icon: LifeBuoy,
  },
  { path: '/settings/account', title: '账户', detail: '查看账号信息与修改密码', icon: UserRound },
  {
    path: '/settings/appearance',
    title: '外观',
    detail: '浅色、深色或跟随系统主题',
    icon: Palette,
  },
  {
    path: '/settings/rules',
    title: '汇报规则',
    detail: '查看汇报周期、时区与生成时间',
    icon: CalendarClock,
  },
  {
    path: '/settings/login',
    title: '登录方式',
    detail: '配置钉钉登录与授权',
    icon: UserRound,
    admin: true,
  },
  {
    path: '/settings/models',
    title: '模型服务管理',
    detail: '配置模型 API、服务连接与用途',
    icon: Cpu,
    admin: true,
  },
  {
    path: '/settings/usage',
    title: '模型用量',
    detail: '查看调用状态、耗时与 Token 用量',
    icon: ChartColumn,
    admin: true,
  },
]
