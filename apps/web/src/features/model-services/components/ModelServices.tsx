import { protocolPurpose } from '@web/features/model-services/types'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import modelServicesStyles from '../styles/model-services.module.css'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { EnvironmentServices } from '@web/features/model-services/components/service/EnvironmentServices'
import { ModelCheckResult } from '@web/features/model-services/components/testing/ModelCheckResult'
import { ModelOptions } from '@web/features/model-services/components/catalog/ModelOptions'
import { ModelPicker } from '@web/features/model-services/components/catalog/ModelPicker'
import { ModelTestDialog } from '@web/features/model-services/components/testing/ModelTestDialog'
import { RemoveServiceDialog } from '@web/features/model-services/components/service/RemoveServiceDialog'
import { Routing } from '@web/features/model-services/components/Routing'
import { ServiceConnectionFields } from '@web/features/model-services/components/service/ServiceConnectionFields'
import { ServiceEditor } from '@web/features/model-services/components/service/ServiceEditor'
import { ServiceList } from '@web/features/model-services/components/service/ServiceList'
import { ServiceModelLibrary } from '@web/features/model-services/components/service/ServiceModelLibrary'
import { UnsavedKeysDialog } from '@web/features/model-services/components/service/UnsavedKeysDialog'
import { useModelServiceController } from '@web/features/model-services/hooks/useModelServiceController'
import { Plus } from 'lucide-react'

export function ModelServices() {
  const {
    workspace,
    tab,
    setTab,
    busy,
    setBusy,
    error,
    setError,
    conflict,
    setActiveModel,
    picker,
    setPicker,
    modelOpen,
    setModelOpen,
    testPurpose,
    setTestPurpose,
    removeOpen,
    setRemoveOpen,
    resource,
    services,
    drafts,
    draft,
    allServices,
    dirty,
    connectionReady,
    keys,
    setKeys,
    blocker,
    model,
    automaticMatch,
    updateModel,
    handleError,
    catalog,
    check,
    checkOpen,
    setCheckOpen,
    testOpen,
    setTestOpen,
    request,
    update,
    select,
    changeAddress,
    save,
    remove,
    createService,
    addModels,
    usesFor,
    changeKey,
  } = useModelServiceController()

  return (
    <div className={`${layoutStyles['settings-page']} ${modelServicesStyles['model-management']}`}>
      <PageHeader
        placement="below"
        title="模型服务管理"
        description="连接你信任的模型，为不同工作选择合适的能力。"
        actions={
          tab === 'services' &&
          draft && (
            <button
              className={controlsStyles.primary}
              disabled={!!busy || !resource.data}
              onClick={createService}
            >
              <Plus size={16} />
              添加服务
            </button>
          )
        }
      />
      <div
        className={`${layoutStyles['tabs']} ${modelServicesStyles['slot-tabs']}`}
        role="tablist"
        aria-label="模型管理页面"
      >
        <button
          role="tab"
          aria-selected={tab === 'services'}
          data-active={tab === 'services'}
          disabled={!!busy}
          onClick={() => setTab('services')}
        >
          服务配置
        </button>
        <button
          role="tab"
          aria-selected={tab === 'routing'}
          data-active={tab === 'routing'}
          disabled={!!busy}
          onClick={() => setTab('routing')}
        >
          用途分配
        </button>
      </div>
      <ErrorNotice retry={resource.refresh}>{resource.error}</ErrorNotice>
      <EnvironmentServices
        resource={resource}
        busy={busy}
        setBusy={setBusy}
        notify={workspace.notify}
        handleError={handleError}
      />
      {tab === 'routing' ? (
        <Routing
          services={services}
          initial={resource.data?.routing ?? null}
          refresh={resource.refresh}
        />
      ) : (
        <div className={modelServicesStyles['service-workspace']}>
          <ServiceList
            compact
            disabled={!!busy}
            selectedId={draft?.id}
            allServices={allServices}
            resource={resource}
            createService={createService}
            drafts={drafts}
            services={services}
            keys={keys}
            usesFor={usesFor}
            select={select}
          />
          <div className={modelServicesStyles['service-workspace-detail']}>
            {draft ? (
              <ServiceEditor
                busy={busy}
                dirty={dirty}
                draft={draft}
                setRemoveOpen={setRemoveOpen}
                update={update}
                setKeys={setKeys}
                connectionReady={connectionReady}
                error={error}
                conflict={conflict}
                save={save}
              >
                <ServiceConnectionFields
                  draft={draft}
                  busy={busy}
                  changeAddress={changeAddress}
                  update={update}
                  keyValue={keys[draft.id] || ''}
                  onKeyChange={changeKey}
                />
                <ServiceModelLibrary
                  draft={draft}
                  busy={busy}
                  connectionReady={connectionReady}
                  usesFor={usesFor}
                  onAdd={(mode) => {
                    if (mode === 'catalog') {
                      setPicker('catalog')
                      void request('models')
                    } else {
                      setError('')
                      setPicker('manual')
                    }
                  }}
                  onConfigure={(item) => {
                    setActiveModel(item.id)
                    setError('')
                    setModelOpen(true)
                  }}
                  onTest={(item) => {
                    setActiveModel(item.id)
                    setTestPurpose(protocolPurpose(item.protocol))
                    setError('')
                    setTestOpen(true)
                  }}
                />
              </ServiceEditor>
            ) : (
              <div className={modelServicesStyles['service-welcome']}>
                <h3>为工作接入合适的模型</h3>
                <p>选择一个服务查看连接与模型，或添加新服务。</p>
                <div className={modelServicesStyles['service-flow']}>
                  <span>连接服务</span>
                  <span>选择并测试模型</span>
                  <span>分配用途</span>
                </div>
                <button
                  disabled={!!busy || !resource.data}
                  className={controlsStyles['primary']}
                  onClick={createService}
                >
                  <Plus size={16} />
                  添加服务
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      {picker && draft && (
        <ModelPicker
          picker={picker}
          draft={draft}
          busy={busy}
          setPicker={setPicker}
          addModels={addModels}
          error={error}
          catalog={catalog}
          setError={setError}
        />
      )}
      <ModelOptions
        modelOpen={modelOpen}
        model={model}
        draft={draft}
        setModelOpen={setModelOpen}
        busy={busy}
        updateModel={updateModel}
        automaticMatch={automaticMatch}
        setTestPurpose={setTestPurpose}
        update={update}
        setActiveModel={setActiveModel}
        error={error}
      />
      <ModelCheckResult checkOpen={checkOpen} check={check} setCheckOpen={setCheckOpen} />
      <RemoveServiceDialog
        removeOpen={removeOpen}
        draft={draft}
        busy={busy}
        setRemoveOpen={setRemoveOpen}
        error={error}
        remove={remove}
      />
      <ModelTestDialog
        testOpen={testOpen}
        draft={draft}
        busy={busy}
        setTestOpen={setTestOpen}
        model={model}
        testPurpose={testPurpose}
        setTestPurpose={setTestPurpose}
        request={request}
      />
      <UnsavedKeysDialog
        blocker={blocker}
        busy={busy}
        keys={keys}
        save={save}
        drafts={drafts}
        services={services}
        setKeys={setKeys}
        error={error}
      />
    </div>
  )
}
