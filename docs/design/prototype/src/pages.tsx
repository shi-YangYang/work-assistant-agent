import React, { useEffect, useRef, useState } from 'react'
import {
  Avatar,
  Badge,
  Button,
  Empty,
  Header,
  Icon,
  Modal,
  Segments,
  Select,
  Tool,
} from './components'
import { type Work, statuses } from './data'

type SharedProps = {
  works: Work[]
  setWorks: React.Dispatch<React.SetStateAction<Work[]>>
  notify: (v: string) => void
}

export function Assistant({
  navigate,
  notify,
  works,
  setWorks,
  role,
}: SharedProps & { navigate: (id: string) => void; role: string }) {
  const [conversation, setConversation] = useState('')
  const [history, setHistory] = useState(false)
  const [input, setInput] = useState('')
  const [attachMenu, setAttachMenu] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const attachRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!attachMenu) return
    const close = (event: PointerEvent) => {
      if (!attachRef.current?.contains(event.target as Node)) setAttachMenu(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [attachMenu])
  const [messages, setMessages] = useState<string[]>([])
  const [thinking, setThinking] = useState(false)
  const [created, setCreated] = useState(false)
  const [attachments, setAttachments] = useState<string[]>([])
  const [model, setModel] = useState('工作助手')
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (messages.length && scrollRef.current)
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, thinking])
  const send = (text = input) => {
    if (!text.trim() || thinking) return
    setMessages((m) => [...m, text.trim()])
    setInput('')
    setThinking(true)
    if (!conversation) setConversation(text.slice(0, 16))
    setTimeout(() => setThinking(false), 650)
  }
  return (
    <div className={`chat-page ${!conversation ? 'is-welcome' : ''}`}>
      <div className="chat-toolbar">
        <div>
          <Icon name="MessageSquare" size={17} />
          <span>{conversation || '工作助手'}</span>
          <span className="chat-date">{conversation ? '今天' : '随时为你准备'}</span>
        </div>
        <div className="chat-tools">
          <Tool
            label="新建会话"
            icon="SquarePen"
            onClick={() => {
              setConversation('')
              setMessages([])
              setCreated(false)
            }}
          />
          <Tool label="会话列表" icon="History" onClick={() => setHistory(!history)} />
        </div>
        {history && (
          <div className="history-panel popover">
            <span className="popover-label">最近的会话</span>
            {['本周团队进展', '官网上线验收安排', '整理客户回访记录'].map((name, i) => (
              <button
                key={name}
                onClick={() => {
                  setConversation(name)
                  setMessages([])
                  setHistory(false)
                }}
              >
                <Icon name="MessageSquare" size={16} />
                <span>
                  {name}
                  <small>{i === 0 ? '今天' : '昨天'}</small>
                </span>
                {name === conversation && <Icon name="Check" size={14} />}
              </button>
            ))}
            <button
              onClick={() => {
                setConversation('')
                setMessages([])
                setHistory(false)
              }}
            >
              <Icon name="Plus" size={16} />
              新的对话
            </button>
          </div>
        )}
      </div>
      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-reading">
          {!conversation ? (
            <div className="chat-welcome">
              <div className="welcome-orbit" aria-hidden="true">
                <span />
                <span />
                <div>
                  <Icon name="Sparkles" size={30} />
                </div>
              </div>
              <div className="welcome-label">
                <span /> 你的工作伙伴
              </div>
              <h1>今天，想推进什么？</h1>
              <p>从一个想法、一份材料，或手头的工作开始。</p>
            </div>
          ) : (
            <>
              {messages.length === 0 && (
                <div className="user-message">
                  <p>
                    {role === '管理员'
                      ? '帮我看看这周团队的进度，有哪些事情需要我跟进？'
                      : '帮我梳理一下这周的工作，看看有哪些需要优先跟进。'}
                  </p>
                </div>
              )}
              {messages.length === 0 && (
                <article className="assistant-message">
                  <div className="assistant-name">
                    <span>
                      <Icon name="Sparkles" size={17} />
                    </span>
                    工作助手<small>刚刚</small>
                  </div>
                  <div className="message-body">
                    <details className="source-result">
                      <summary>
                        <span className="source-check">
                          <Icon name="Check" size={12} />
                        </span>
                        {role === '管理员' ? '已整理团队进展' : '已整理你的工作'}
                        <span className="source-count">3 条来源</span>
                        <Icon name="ChevronDown" size={14} />
                      </summary>
                      <div className="source-items">
                        {['官网上线验收 · 林悦', '支付接口联调 · 许言', '客户试用反馈 · 陈一'].map(
                          (name) => (
                            <button key={name} onClick={() => navigate('work')}>
                              <Icon name="FileText" size={15} />
                              <span>{name}</span>
                              <Icon name="ArrowUpRight" size={14} />
                            </button>
                          ),
                        )}
                      </div>
                    </details>
                    <h2>
                      整体进展平稳，
                      <br className="mobile-break" />
                      有两件事值得关注。
                    </h2>
                    <p>
                      官网验收和产品迭代正在推进。当前最需要你协调的是支付接口的测试账号，以及明天的客户反馈安排。
                    </p>
                    <div className="insight-list">
                      <button onClick={() => navigate('work')}>
                        <span className="insight-index amber">01</span>
                        <div>
                          <strong>支付接口联调等待外部支持</strong>
                          <p>许言已完成内部检查，仍缺少合作方测试账号。</p>
                          <span className="inline-meta">
                            <span className="tiny-dot amber" />
                            有阻碍<span>·</span>今天需要跟进
                          </span>
                        </div>
                        <Icon name="ArrowUpRight" size={17} />
                      </button>
                      <button onClick={() => navigate('work')}>
                        <span className="insight-index">02</span>
                        <div>
                          <strong>客户试用反馈，明天确认下一步</strong>
                          <p>陈一正在归类首批反馈，建议先对齐处理优先级。</p>
                          <span className="inline-meta">
                            客户体验<span>·</span>明天
                          </span>
                        </div>
                        <Icon name="ArrowUpRight" size={17} />
                      </button>
                    </div>
                    <p className="assistant-conclusion">
                      建议先联系合作方提供账号，让联调继续推进。我也可以把这件事加入你的工作。
                    </p>
                    <section className="approval-wrap">
                      <header>
                        <span>
                          <Icon name="ListTodo" size={15} /> 新建工作
                        </span>
                        <span className={`approval-state ${created ? 'complete' : ''}`}>
                          {created ? '已完成' : '需要你的确认'}
                        </span>
                      </header>
                      <div className="proposal">
                        <span className="proposal-icon">
                          <Icon name="ListPlus" size={19} />
                        </span>
                        <div>
                          <strong>{created ? '已加入我的工作' : '跟进合作方测试账号'}</strong>
                          <small>
                            {created ? '已保存，你可以继续更新进展' : '负责人：我　 ·　 截止：今天'}
                          </small>
                        </div>
                        <Button
                          icon={created ? 'Check' : 'Plus'}
                          kind={created ? 'quiet' : 'primary'}
                          disabled={created}
                          onClick={() => {
                            setCreated(true)
                            setWorks([
                              {
                                id: 'WK-025',
                                title: '跟进合作方测试账号',
                                summary: '联系合作方提供测试账号，推动支付接口联调。',
                                status: '待处理',
                                owner: '我',
                                date: '今天',
                                tag: '产品迭代',
                              },
                              ...works,
                            ])
                            notify('示例工作已创建')
                          }}
                        >
                          {created ? '已创建' : '确认创建'}
                        </Button>
                      </div>
                    </section>
                    <div className="answer-actions">
                      <Tool
                        label="复制回答"
                        icon="Copy"
                        onClick={() => {
                          navigator.clipboard?.writeText(
                            '整体进展平稳，支付接口联调与客户反馈需要优先跟进。',
                          )
                          notify('已复制示例回答')
                        }}
                      />
                      <Tool
                        label="有帮助"
                        icon="ThumbsUp"
                        onClick={() => notify('已记录本次原型反馈')}
                      />
                      <button
                        className="text-action"
                        onClick={() => navigate(role === '管理员' ? 'team' : 'work')}
                      >
                        查看{role === '管理员' ? '团队看板' : '我的工作'}
                        <Icon name="ArrowUpRight" size={14} />
                      </button>
                    </div>
                  </div>
                </article>
              )}
              {messages.map((message, index) => (
                <React.Fragment key={index}>
                  <div className="user-message">
                    <p>{message}</p>
                  </div>
                  <article className="assistant-message">
                    <div className="assistant-name">
                      <span>
                        <Icon name="Sparkles" size={17} />
                      </span>
                      工作助手
                    </div>
                    <div className="message-body">
                      {thinking && index === messages.length - 1 ? (
                        <div className="thinking">
                          <i />
                          <i />
                          <i />
                          <span>正在整理</span>
                        </div>
                      ) : (
                        <>
                          <p>
                            这是对话展示示例。正式接入后，这里将使用你配置的模型处理消息、查询工作，并展示需要你确认的操作。
                          </p>
                          <Button kind="quiet" icon="ArrowUpRight" onClick={() => navigate('work')}>
                            查看示例工作
                          </Button>
                        </>
                      )}
                    </div>
                  </article>
                </React.Fragment>
              ))}
            </>
          )}
        </div>
      </div>
      <div className="composer-area">
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
        >
          {attachments.length > 0 && (
            <div className="attachment-preview">
              {attachments.map((name) => (
                <span key={name}>
                  <Icon name="FileText" size={15} />
                  {name}
                  <button
                    type="button"
                    aria-label={`移除${name}`}
                    onClick={() => setAttachments(attachments.filter((f) => f !== name))}
                  >
                    <Icon name="X" size={13} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="发消息，或告诉我你想推进的工作…"
            aria-label="消息内容"
            rows={2}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                send()
              }
            }}
          />
          <div className="composer-toolbar">
            <div>
              <div
                className="prompt-add-wrap"
                ref={attachRef}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') setAttachMenu(false)
                }}
              >
                <button
                  type="button"
                  className={`prompt-add ${attachMenu ? 'open' : ''}`}
                  aria-label="添加内容"
                  aria-expanded={attachMenu}
                  onClick={() => setAttachMenu(!attachMenu)}
                >
                  <Icon name="Plus" size={20} />
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  hidden
                  onChange={(event) =>
                    setAttachments(Array.from(event.target.files ?? []).map((f) => f.name))
                  }
                />
                {attachMenu && (
                  <div className="prompt-add-menu popover">
                    <button
                      type="button"
                      onClick={() => {
                        fileRef.current!.accept = 'image/*'
                        fileRef.current?.click()
                        setAttachMenu(false)
                      }}
                    >
                      <Icon name="Image" />
                      <span>
                        添加图片<small>截图、照片或工作现场</small>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        fileRef.current!.accept = ''
                        fileRef.current?.click()
                        setAttachMenu(false)
                      }}
                    >
                      <Icon name="FileText" />
                      <span>
                        添加文件<small>文档、表格或语音材料</small>
                      </span>
                    </button>
                  </div>
                )}
              </div>
              <Tool
                label="语音输入"
                icon="Mic"
                type="button"
                onClick={() => notify('此原型仅展示录音入口，不会开启麦克风')}
              />
              <Select
                label="对话模式"
                value={model}
                options={['工作助手', '直接问答']}
                onChange={setModel}
              />
            </div>
            <button
              className="send-button"
              aria-label="发送消息"
              disabled={!input.trim() || thinking}
            >
              <Icon name="ArrowUp" size={19} />
            </button>
          </div>
        </form>
        {!conversation && (
          <div className="welcome-shortcuts">
            {[
              {
                icon: 'ListTodo',
                title: '梳理工作',
                detail: '把待办变成下一步',
                text: '帮我整理今天需要跟进的工作',
              },
              {
                icon: 'FileText',
                title: '整理汇报',
                detail: '让进展清晰可见',
                text: '帮我根据今天的工作整理日报',
              },
              {
                icon: 'ScanText',
                title: '解读材料',
                detail: '从文档中提炼重点',
                text: '帮我提炼材料中的重要信息',
              },
            ].map((item) => (
              <button key={item.title} onClick={() => send(item.text)}>
                <span className="shortcut-icon">
                  <Icon name={item.icon} size={19} />
                </span>
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
                <Icon name="ArrowUpRight" size={15} />
              </button>
            ))}
            <button className="recent-conversation" onClick={() => setConversation('本周团队进展')}>
              <Icon name="History" size={16} />
              <span>继续上次的对话</span>
              <strong>本周团队进展</strong>
              <Icon name="ArrowRight" size={15} />
            </button>
          </div>
        )}
        <div className="composer-hint">
          <span>示例数据 · 不连接真实模型</span>
          <span>
            Enter 发送 <span>·</span> Shift + Enter 换行
          </span>
        </div>
      </div>
    </div>
  )
}

function WorkDetail({
  work,
  onClose,
  onSave,
}: {
  work: Work
  onClose: () => void
  onSave: (work: Work) => void
}) {
  const [draft, setDraft] = useState(work)
  return (
    <Modal drawer title="工作详情" onClose={onClose}>
      <div className="detail-id">
        <Icon name="CircleCheck" size={16} />
        {work.id}
        <span>更新于 今天 10:24</span>
      </div>
      <h2 className="detail-title">{work.title}</h2>
      <div className="detail-properties">
        <label>状态</label>
        <Select
          label="工作状态"
          options={statuses.slice(1)}
          value={draft.status}
          onChange={(status) => setDraft({ ...draft, status })}
        />
        <label>负责人</label>
        <span className="person">
          <Avatar name={work.owner} small />
          {work.owner}
        </span>
        <label>截止时间</label>
        <span>
          <Icon name="CalendarDays" size={15} />
          {work.date}
        </span>
        <label>所属项目</label>
        <span>
          <Icon name="FolderClosed" size={15} />
          {work.tag}
        </span>
      </div>
      <div className="detail-section">
        <h3>工作说明</h3>
        <p>{work.summary}</p>
      </div>
      <div className="detail-section">
        <h3>下一步</h3>
        <textarea
          aria-label="下一步"
          value={draft.summary}
          onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
        />
      </div>
      <div className="detail-section">
        <h3>最近进展</h3>
        <div className="timeline">
          <span />
          <div>
            <strong>补充了工作进展</strong>
            <p>{work.summary}</p>
            <small>{work.owner} · 今天 10:24</small>
          </div>
        </div>
      </div>
      <footer className="dialog-footer">
        <Button onClick={onClose}>取消</Button>
        <Button kind="primary" icon="Check" onClick={() => onSave(draft)}>
          保存修改
        </Button>
      </footer>
    </Modal>
  )
}
function CreateWork({
  onClose,
  onCreate,
}: {
  onClose: () => void
  onCreate: (title: string) => void
}) {
  const [title, setTitle] = useState('')
  return (
    <Modal title="新建工作" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (title.trim()) onCreate(title.trim())
        }}
        className="create-form"
      >
        <label>
          工作名称
          <input
            autoFocus
            placeholder="你要推进什么事情？"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            maxLength={100}
          />
        </label>
        <label>
          工作说明
          <textarea placeholder="写下目标、背景或下一步…" />
        </label>
        <footer className="dialog-footer">
          <Button type="button" onClick={onClose}>
            取消
          </Button>
          <Button kind="primary" disabled={!title.trim()}>
            创建工作
            <Icon name="ArrowRight" size={15} />
          </Button>
        </footer>
      </form>
    </Modal>
  )
}
export function WorkPage({ works, setWorks, notify }: SharedProps) {
  const [tab, setTab] = useState('全部工作')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('全部状态')
  const [empty, setEmpty] = useState(false)
  const [selected, setSelected] = useState<Work | null>(null)
  const [create, setCreate] = useState(false)
  const visible = empty
    ? []
    : works.filter(
        (w) =>
          `${w.title}${w.summary}`.includes(query) &&
          (status === '全部状态' || w.status === status) &&
          (tab === '全部工作' ||
            (tab === '进行中' ? w.status === '进行中' : w.status === '已完成')),
      )
  return (
    <>
      <Header title="我的工作" subtitle="理清优先级，一件一件向前推进。">
        <button className="subtle-button" onClick={() => setEmpty(!empty)}>
          <Icon name={empty ? 'List' : 'ScanLine'} size={15} />
          {empty ? '查看有数据状态' : '预览空状态'}
        </button>
        <Button kind="primary" icon="Plus" onClick={() => setCreate(true)}>
          新建工作
        </Button>
      </Header>
      <section className="work-surface">
        <div className="list-tabs">
          <Segments
            items={['全部工作', '进行中', '已完成']}
            value={tab}
            onChange={setTab}
            label="工作分类"
          />
          <Tool label="刷新工作" icon="RefreshCw" onClick={() => notify('示例工作已刷新')} />
        </div>
        <div className="list-toolbar">
          <label className="search-input">
            <Icon name="Search" size={17} />
            <input
              aria-label="搜索工作"
              placeholder="搜索工作…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <kbd>/</kbd>
          </label>
          <div className="filter-group">
            <Select label="筛选工作状态" options={statuses} value={status} onChange={setStatus} />
            <button
              className="subtle-button"
              onClick={() => {
                setQuery('')
                setStatus('全部状态')
                setTab('全部工作')
              }}
            >
              <Icon name="SlidersHorizontal" size={15} />
              <span>重置筛选</span>
            </button>
          </div>
        </div>
        {visible.length ? (
          <>
            <div className="work-table-head">
              <span>工作事项</span>
              <span>状态</span>
              <span>截止时间</span>
              <span />
            </div>
            <div className="work-rows">
              {visible.map((work) => (
                <button key={work.id} className="work-row" onClick={() => setSelected(work)}>
                  <span
                    className={`work-status-icon ${work.status === '已完成' ? 'complete' : ''}`}
                  >
                    <Icon
                      name={
                        work.status === '已完成'
                          ? 'CircleCheck'
                          : work.status === '有阻碍'
                            ? 'CircleAlert'
                            : work.status === '进行中'
                              ? 'CircleDashed'
                              : 'Circle'
                      }
                      size={19}
                    />
                  </span>
                  <div className="work-title">
                    <strong>{work.title}</strong>
                    <p>{work.summary}</p>
                    <span className="work-meta">
                      {work.id}
                      <i /> {work.tag}
                    </span>
                  </div>
                  <Badge status={work.status} />
                  <span className="date-label">{work.date}</span>
                  <span className="row-arrow">
                    <Icon name="ArrowUpRight" size={17} />
                  </span>
                </button>
              ))}
            </div>
            <footer className="list-footer">
              <span>共 {visible.length} 项工作</span>
              <div>
                <button disabled aria-label="上一页">
                  <Icon name="ChevronLeft" size={16} />
                </button>
                <span>1 / 1</span>
                <button disabled aria-label="下一页">
                  <Icon name="ChevronRight" size={16} />
                </button>
              </div>
            </footer>
          </>
        ) : (
          <Empty
            title={query || status !== '全部状态' ? '没有匹配的工作' : '从第一件工作开始'}
            text={
              query || status !== '全部状态'
                ? '试试其他关键词，或调整筛选条件。'
                : '记下要做的事，把想法变成下一步。'
            }
            action={
              <Button icon="Plus" onClick={() => setCreate(true)}>
                新建工作
              </Button>
            }
          />
        )}
      </section>
      {selected && (
        <WorkDetail
          work={selected}
          onClose={() => setSelected(null)}
          onSave={(value) => {
            setWorks(works.map((w) => (w.id === value.id ? value : w)))
            setSelected(null)
            notify('示例工作已更新')
          }}
        />
      )}{' '}
      {create && (
        <CreateWork
          onClose={() => setCreate(false)}
          onCreate={(title) => {
            setWorks([
              {
                id: `WK-${Date.now().toString().slice(-3)}`,
                title,
                summary: '在这里补充工作的目标与下一步。',
                status: '待处理',
                owner: '我',
                date: '今天',
                tag: '我的工作',
              },
              ...works,
            ])
            setEmpty(false)
            setTab('全部工作')
            setStatus('全部状态')
            setQuery('')
            setCreate(false)
            notify('示例工作已创建')
          }}
        />
      )}
    </>
  )
}

export function TeamPage({ works, setWorks, notify }: SharedProps) {
  const [tab, setTab] = useState('工作进展')
  const [period, setPeriod] = useState('本周')
  const [selected, setSelected] = useState<Work | null>(null)
  const [query, setQuery] = useState('')
  const [report, setReport] = useState(false)
  const teamWorks = works.filter((w) => w.owner !== '我')
  const blocked = teamWorks.filter((w) => w.status === '有阻碍')
  const names = ['林悦', '陈一', '许言', '周可'].filter((n) => n.includes(query))
  return (
    <>
      <Header title="团队看板" subtitle="了解每个人的进展，看见需要你支持的地方。">
        <div className="updated-at">
          <span className="tiny-dot green" />
          刚刚更新
        </div>
        <Button icon="RefreshCw" onClick={() => notify('示例看板已刷新')}>
          刷新
        </Button>
      </Header>
      <div className="team-summary">
        <div>
          <span>正在推进</span>
          <strong>
            {teamWorks.filter((w) => w.status !== '已完成').length}
            <small>项工作</small>
          </strong>
          <p>来自 4 位团队成员</p>
        </div>
        <div>
          <span>需要支持</span>
          <strong className="attention-number">
            {blocked.length}
            <small>项阻碍</small>
          </strong>
          <p>{blocked.length ? '支付接口联调等待测试账号' : '暂无需要协调的阻碍'}</p>
        </div>
        <div>
          <span>本周已完成</span>
          <strong>
            {teamWorks.filter((w) => w.status === '已完成').length}
            <small>项工作</small>
          </strong>
          <p>每一步推进，都值得被看见</p>
        </div>
        <div className="team-avatar-summary">
          <div>
            {['林悦', '陈一', '许言', '周可'].map((name) => (
              <Avatar name={name} key={name} />
            ))}
          </div>
          <span>4 位成员已更新进展</span>
        </div>
      </div>
      {blocked.length > 0 && (
        <section className="team-attention">
          <div className="attention-mark">
            <Icon name="Flag" size={17} />
          </div>
          <div>
            <strong>有一件事需要你协调</strong>
            <span>许言正在等待合作方提供测试账号，支付联调暂时受阻。</span>
          </div>
          <Button kind="quiet" onClick={() => setSelected(works.find((w) => w.id === 'WK-022')!)}>
            查看工作
            <Icon name="ArrowRight" size={15} />
          </Button>
        </section>
      )}
      <section className="work-surface team-surface">
        <div className="list-tabs">
          <Segments
            items={['工作进展', '工作汇报']}
            value={tab}
            onChange={setTab}
            label="团队视图"
          />
          <Select
            label="时间范围"
            options={['本周', '今天', '上周']}
            value={period}
            onChange={setPeriod}
          />
        </div>
        <div className="list-toolbar">
          <label className="search-input">
            <Icon name="Search" size={17} />
            <input
              aria-label="搜索成员"
              placeholder="搜索成员…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <span className="muted small">
            {period} · {names.length} 位成员
          </span>
        </div>
        <div className="team-table-head">
          <span>成员</span>
          <span>{tab === '工作进展' ? '最近进展' : '本周汇报'}</span>
          <span>状态</span>
          <span>更新</span>
        </div>
        {names.map((name, i) => {
          const work = works.find((w) => w.owner === name)!
          return (
            <button
              key={name}
              className="team-row"
              onClick={() => (tab === '工作进展' ? setSelected(work) : setReport(true))}
            >
              <span className="person">
                <Avatar name={name} />
                <strong>{name}</strong>
              </span>
              <div>
                <strong>{tab === '工作进展' ? work.title : `${name}的本周工作汇报`}</strong>
                <p>
                  {tab === '工作进展'
                    ? work.summary
                    : i === 2
                      ? '周报待补充，已发送提醒。'
                      : '已整理本周工作、进展与下一步安排。'}
                </p>
              </div>
              <Badge status={tab === '工作进展' ? work.status : i === 2 ? '待提交' : '已提交'} />
              <span className="date-label">
                {i === 0 ? '10:24' : i === 1 ? '09:48' : '昨天'}
                <Icon name="ChevronRight" size={15} />
              </span>
            </button>
          )
        })}
        {!names.length && <Empty title="没有找到成员" text="试试其他姓名。" />}
        <footer className="list-footer">
          <span>{tab === '工作进展' ? '点击工作查看进展详情' : '点击汇报阅读完整内容'}</span>
          <span>示例周期：9月21日 — 9月27日</span>
        </footer>
      </section>
      {selected && (
        <WorkDetail
          work={selected}
          onClose={() => setSelected(null)}
          onSave={(value) => {
            setWorks(works.map((w) => (w.id === value.id ? value : w)))
            setSelected(null)
            notify('示例工作已更新')
          }}
        />
      )}{' '}
      {report && <ReportDetail onClose={() => setReport(false)} />}
    </>
  )
}

function ReportDetail({ onClose }: { onClose: () => void }) {
  return (
    <Modal drawer title="本周工作汇报" onClose={onClose}>
      <div className="report-byline">
        <Avatar name="林悦" small />
        林悦<span>9月21日 — 9月27日</span>
        <Badge status="已提交" />
      </div>
      <div className="report-paper">
        <span className="eyebrow">WEEKLY REVIEW</span>
        <h2>有序推进，聚焦交付。</h2>
        <p>本周重点推进官网上线与产品评审，两项工作均按计划进行。</p>
        <h3>01　本周完成</h3>
        <ul>
          <li>完成官网首页与产品页的首轮文案核对。</li>
          <li>梳理评审结论，明确对应负责人及交付节点。</li>
        </ul>
        <h3>02　正在推进</h3>
        <p>与设计同事进行最后一轮内容调整，准备上线前的整体检查。</p>
        <h3>03　下一步安排</h3>
        <p>完成官网上线验收，并跟进产品评审行动项的落实情况。</p>
      </div>
    </Modal>
  )
}
export function ReportsPage({ notify }: { notify: (v: string) => void }) {
  const [tab, setTab] = useState('汇报待办')
  const [kind, setKind] = useState('周报')
  const [empty, setEmpty] = useState(false)
  const [detail, setDetail] = useState(false)
  return (
    <>
      <Header title="我的报告" subtitle="回顾已经走过的路，也看清下一步。">
        <button className="subtle-button" onClick={() => setEmpty(!empty)}>
          <Icon name="ScanLine" size={15} />
          {empty ? '查看有数据状态' : '预览空状态'}
        </button>
        <Button icon="CalendarDays" onClick={() => notify('示例安排：每周五 18:00 提交周报')}>
          汇报安排
        </Button>
      </Header>
      <section className="work-surface">
        <div className="list-tabs">
          <div className="line-tabs">
            {['汇报待办', '全部报告'].map((t) => (
              <button key={t} aria-selected={tab === t} onClick={() => setTab(t)}>
                {t}
                {t === '汇报待办' && <span>{empty ? 0 : 1}</span>}
              </button>
            ))}
          </div>
          <Segments items={['日报', '周报']} value={kind} onChange={setKind} label="报告类型" />
        </div>
        {empty ? (
          <Empty title="暂时没有待办，专注眼前的工作。" text="新的汇报安排会出现在这里。" />
        ) : (
          <>
            <div className="report-list">
              <button className="report-item" onClick={() => setDetail(true)}>
                <span className="report-file">
                  <Icon name="FileText" size={23} />
                </span>
                <div>
                  <span className="eyebrow">{tab === '汇报待办' ? '即将到期' : '最新汇报'}</span>
                  <h3>本{kind === '周报' ? '周' : '日'}工作汇报</h3>
                  <p>
                    9月21日 — 9月27日<span>·</span>周五 18:00 前提交
                  </p>
                </div>
                <Badge status={tab === '汇报待办' ? '待提交' : '已提交'} />
                <Icon name="ArrowUpRight" size={18} />
              </button>
              {tab === '全部报告' && (
                <button className="report-item" onClick={() => setDetail(true)}>
                  <span className="report-file">
                    <Icon name="FileText" size={23} />
                  </span>
                  <div>
                    <h3>上{kind === '周报' ? '周' : '日'}工作汇报</h3>
                    <p>9月14日 — 9月20日</p>
                  </div>
                  <Badge status="已提交" />
                  <Icon name="ArrowUpRight" size={18} />
                </button>
              )}
            </div>
            <div className="report-assist">
              <Icon name="Sparkles" size={19} />
              <span>从日常记录开始，汇报自然成形。</span>
              <button
                onClick={() => {
                  setDetail(true)
                  notify('打开示例报告')
                }}
              >
                查看报告
                <Icon name="ArrowRight" size={14} />
              </button>
            </div>
          </>
        )}
      </section>
      {detail && <ReportDetail onClose={() => setDetail(false)} />}
    </>
  )
}

export function ModelsPage({ notify }: { notify: (v: string) => void }) {
  const [tab, setTab] = useState('服务与模型')
  const [service, setService] = useState('阿里云百炼')
  const [testing, setTesting] = useState(false)
  const [tested, setTested] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [models, setModels] = useState(['qwen-plus', 'qwen-turbo', 'qwen3-asr-flash'])
  const [adding, setAdding] = useState(false)
  const [newModel, setNewModel] = useState('')
  const [reasoning, setReasoning] = useState('默认')
  const [stream, setStream] = useState(true)
  const [usage, setUsage] = useState([
    '阿里云百炼 / qwen-plus',
    '阿里云百炼 / qwen-plus',
    '阿里云百炼 / qwen3-asr-flash',
  ])
  const [provider, setProvider] = useState('OpenAI 兼容')
  const services = ['阿里云百炼', 'DeepSeek']
  const displayed = service === 'DeepSeek' ? ['deepseek-chat', 'deepseek-reasoner'] : models
  return (
    <>
      <Header title="模型服务管理" subtitle="连接你信任的模型，为不同工作选择合适的能力。">
        <span className="save-state">
          <Icon name={dirty ? 'Circle' : 'Check'} size={14} />
          {dirty ? '有未保存的修改' : '所有更改已保存'}
        </span>
        <Button
          kind="primary"
          icon="Plus"
          onClick={() => {
            setService('新服务')
            setDirty(true)
            setTab('服务与模型')
          }}
        >
          添加服务
        </Button>
      </Header>
      <div className="model-main-tabs">
        <Segments
          items={['服务与模型', '用途分配']}
          value={tab}
          onChange={setTab}
          label="模型管理视图"
        />
      </div>
      {tab === '服务与模型' ? (
        <section className="model-workspace">
          <aside className="service-list">
            <span className="eyebrow">
              模型服务 <span>{service === '新服务' ? 3 : 2}</span>
            </span>
            {[...services, ...(service === '新服务' ? ['新服务'] : [])].map((name, i) => (
              <button
                className={service === name ? 'selected' : ''}
                onClick={() => {
                  setService(name)
                  setTested(false)
                }}
                key={name}
              >
                <span className="provider-icon">
                  <Icon name={i === 0 ? 'Cloud' : 'Orbit'} size={19} />
                </span>
                <div>
                  <strong>{name}</strong>
                  <small>{i === 0 ? models.length : i === 1 ? 2 : 0} 个模型</small>
                </div>
                {service === name && <Icon name="ChevronRight" size={14} />}
              </button>
            ))}
            <div className="service-note">
              <Icon name="LockKeyhole" size={15} />
              <span>密钥仅在服务端保存</span>
            </div>
          </aside>
          <div className="service-editor" key={service}>
            <div className="service-title">
              <div className="provider-icon large">
                <Icon name={service === '阿里云百炼' ? 'Cloud' : 'Orbit'} size={24} />
              </div>
              <div>
                <h2>{service}</h2>
                <p>{service === '新服务' ? '填写连接信息，开始添加模型' : 'OpenAI 兼容接口'}</p>
              </div>
              {service !== '新服务' && <Badge status="已连接" />}
            </div>
            <section className="model-section">
              <div className="section-heading">
                <h3>连接配置</h3>
                <span>01</span>
              </div>
              <div className="form-grid">
                <label>
                  服务名称
                  <input
                    aria-label="服务名称"
                    defaultValue={service === '新服务' ? '' : service}
                    placeholder="为服务取个名字"
                    onChange={() => setDirty(true)}
                  />
                </label>
                <label>
                  接口协议
                  <Select
                    label="接口协议"
                    options={['OpenAI 兼容', 'Qwen ASR']}
                    value={provider}
                    onChange={(v) => {
                      setProvider(v)
                      setDirty(true)
                    }}
                  />
                </label>
                <label className="wide">
                  API 地址
                  <input
                    aria-label="API 地址"
                    defaultValue={
                      service === '新服务'
                        ? ''
                        : service === '阿里云百炼'
                          ? 'https://dashscope.aliyuncs.com/compatible-mode/v1'
                          : 'https://api.deepseek.com/v1'
                    }
                    placeholder="https://api.example.com/v1"
                    onChange={() => setDirty(true)}
                  />
                </label>
                <label className="wide">
                  API Key
                  <span className="secret-input">
                    <Icon name="KeyRound" size={16} />
                    <input
                      aria-label="API Key"
                      type="password"
                      placeholder={service === '新服务' ? '输入服务密钥' : '已配置 · 输入以更换'}
                      onChange={() => setDirty(true)}
                    />
                    <span>{service === '新服务' ? '未配置' : '已保存'}</span>
                  </span>
                </label>
              </div>
            </section>
            <section className="model-section">
              <div className="section-heading">
                <h3>
                  可用模型
                  <span className="count">{service === '新服务' ? 0 : displayed.length}</span>
                </h3>
                <div>
                  <Button
                    kind="quiet"
                    icon="RefreshCw"
                    onClick={() => notify('原型使用固定模型列表，不向服务商发起请求')}
                  >
                    获取模型
                  </Button>
                  <Button kind="quiet" icon="Plus" onClick={() => setAdding(true)}>
                    手动添加
                  </Button>
                </div>
              </div>
              {service === '新服务' ? (
                <p className="muted model-empty">连接服务后，获取模型或手动添加模型 ID。</p>
              ) : (
                <div className="model-list">
                  {displayed.map((m, i) => (
                    <div key={m}>
                      <Icon name={m.includes('asr') ? 'AudioLines' : 'Box'} size={17} />
                      <span>
                        <strong>{m}</strong>
                        <small>
                          {m.includes('asr')
                            ? '语音转写'
                            : i === 0
                              ? '工作助手、报告生成'
                              : '尚未分配用途'}
                        </small>
                      </span>
                      <Tool
                        label={`配置 ${m}`}
                        icon="SlidersHorizontal"
                        onClick={() => {
                          setNewModel(m)
                          setAdding(true)
                        }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </section>
            <details className="advanced-settings">
              <summary>
                <Icon name="SlidersHorizontal" size={16} />
                <span>生成偏好</span>
                <small>
                  {stream ? '流式输出' : '非流式输出'} · {reasoning}强度
                </small>
                <Icon name="ChevronDown" size={14} />
              </summary>
              <div>
                <label>
                  推理强度
                  <Select
                    label="推理强度"
                    options={['默认', '低', '中', '高']}
                    value={reasoning}
                    onChange={(v) => {
                      setReasoning(v)
                      setDirty(true)
                    }}
                  />
                </label>
                <div className="switch-row">
                  <span>使用流式接口</span>
                  <button
                    aria-label="使用流式接口"
                    role="switch"
                    aria-checked={stream}
                    onClick={() => {
                      setStream(!stream)
                      setDirty(true)
                    }}
                  >
                    <span />
                  </button>
                </div>
              </div>
            </details>
            <footer className="model-footer">
              <span className={tested ? 'test-result' : 'muted'}>
                {tested ? (
                  <>
                    <Icon name="Check" size={15} />
                    示例连接成功
                  </>
                ) : (
                  '仅影响之后发起的请求'
                )}
              </span>
              <div>
                <Button
                  disabled={testing}
                  icon="Zap"
                  onClick={() => {
                    setTesting(true)
                    setTimeout(() => {
                      setTesting(false)
                      setTested(true)
                      notify('原型演示：未实际请求模型服务')
                    }, 700)
                  }}
                >
                  {testing ? '测试中…' : '测试连接'}
                </Button>
                <Button
                  kind="primary"
                  onClick={() => {
                    setDirty(false)
                    notify('示例配置已保存到当前预览')
                  }}
                >
                  保存服务
                </Button>
              </div>
            </footer>
          </div>
        </section>
      ) : (
        <section className="routing-surface">
          <header>
            <h2>让合适的模型，做合适的工作。</h2>
            <p>统一管理工作助手、报告生成与语音转写的模型来源。</p>
          </header>
          {[
            { icon: 'Sparkles', title: '工作助手', text: '理解消息、查询信息、推进业务操作' },
            { icon: 'FileText', title: '报告生成', text: '将日常工作整理为清晰的日报、周报' },
            { icon: 'AudioLines', title: '语音转写', text: '把语音内容转成可检索的文字' },
          ].map((item, index) => (
            <div className="routing-row" key={item.title}>
              <span className="routing-icon">
                <Icon name={item.icon} size={22} />
              </span>
              <div>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </div>
              <Select
                label={`${item.title}模型`}
                value={usage[index]}
                options={
                  index === 2
                    ? ['阿里云百炼 / qwen3-asr-flash']
                    : [
                        '阿里云百炼 / qwen-plus',
                        '阿里云百炼 / qwen-turbo',
                        'DeepSeek / deepseek-chat',
                      ]
                }
                onChange={(v) => {
                  setUsage(usage.map((u, i) => (i === index ? v : u)))
                  setDirty(true)
                }}
              />
            </div>
          ))}
          <footer className="model-footer">
            <span className="muted">调整用途分配，不影响历史内容。</span>
            <Button
              kind="primary"
              onClick={() => {
                setDirty(false)
                notify('示例用途分配已保存')
              }}
            >
              保存分配
            </Button>
          </footer>
        </section>
      )}
      {adding && (
        <Modal
          title={newModel ? '模型配置' : '手动添加模型'}
          onClose={() => {
            setAdding(false)
            setNewModel('')
          }}
        >
          <form
            className="create-form"
            onSubmit={(e) => {
              e.preventDefault()
              if (!models.includes(newModel)) setModels([...models, newModel])
              setAdding(false)
              setNewModel('')
              setDirty(true)
            }}
          >
            <label>
              模型 ID
              <input
                required
                autoFocus
                placeholder="例如 qwen-plus"
                value={newModel}
                onChange={(e) => setNewModel(e.target.value)}
              />
            </label>
            <label>
              推理强度
              <Select
                label="模型推理强度"
                options={['默认', '低', '中', '高']}
                value={reasoning}
                onChange={setReasoning}
              />
            </label>
            <footer className="dialog-footer">
              <Button
                type="button"
                onClick={() => {
                  setAdding(false)
                  setNewModel('')
                }}
              >
                取消
              </Button>
              <Button kind="primary">确定</Button>
            </footer>
          </form>
        </Modal>
      )}
    </>
  )
}
