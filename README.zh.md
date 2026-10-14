# vLLM Production Stack：面向生产环境的 vLLM 部署参考栈

| [**博客**](https://lmcache.github.io) | [**官方文档**](https://docs.vllm.ai/projects/production-stack) | [**Production-Stack Slack 频道**](https://communityinviter.com/apps/vllm-dev/join-vllm-developers-slack) | [**LMCache Slack**](https://join.slack.com/t/lmcacheworkspace/shared_invite/zt-2viziwhue-5Amprc9k5hcIdXT7XevTaQ) | [**意向登记表**](https://forms.gle/mQfQDUXbKfp2St1z7) |

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

## 最新动态

- 📄 Production-Stack [官方文档](https://docs.vllm.ai/projects/production-stack)正式发布！
- ✨ 面向 Lambda Labs、AWS EKS 和 Google GCP 的[云端部署教程](https://github.com/vllm-project/production-stack/tree/main/tutorials)现已推出！
- 🛤️ 2026 年度路线图已发布！[立即参与讨论](https://github.com/vllm-project/production-stack/issues/855)！
- 🔥 vLLM Production Stack 正式发布！欢迎阅读我们于 2025 年 1 月 22 日发布的[发布博客](https://blog.lmcache.ai/2025-01-21-stack-release)。

## 社区活动

我们在以下固定时间段举办**双周（Bi-weekly）**社区会议：

- 每隔一周的周二下午 5:30（太平洋时间 PT）– [添加到日历](https://drive.google.com/uc?export=download&id=1D4SqQiqzdSx_xsEwS0QTd592zd3Xourh)

欢迎所有开发者参加！

## 简介

**vLLM Production Stack** 项目提供了基于 vLLM 构建生产级推理服务栈的参考实现，支持您：

- 🚀 无需修改任何业务应用代码，即可从单个 vLLM 实例无缝扩展至分布式 vLLM 集群部署
- 💻 通过 Web 可视化监控面板实时观测各项核心指标
- 😄 充分享受智能请求路由与 KV Cache 卸载（Offloading）带来的显著性能增益

## 分步实战教程

0. 如何[*安装 Kubernetes 环境（kubectl、helm、minikube 等）*](https://github.com/vllm-project/production-stack/blob/main/tutorials/00-install-kubernetes-env.md)？
1. 如何[*在主流云平台上部署 Production Stack（AWS、GCP、Lambda Labs、Azure）*](https://github.com/vllm-project/production-stack/tree/main/tutorials/cloud_deployments)？
2. 如何[*搭建最小化 vLLM Production Stack*](https://github.com/vllm-project/production-stack/blob/main/tutorials/01-minimal-helm-installation.md)？
3. 如何[*自定义 vLLM 配置（可选）*](https://github.com/vllm-project/production-stack/blob/main/tutorials/02-basic-vllm-config.md)？
4. 如何[*加载您的 LLM 模型权重*](https://github.com/vllm-project/production-stack/blob/main/tutorials/03-load-model-from-pv.md)？
5. 如何[*在 vLLM Production Stack 中启动多个不同 LLM 模型*](https://github.com/vllm-project/production-stack/blob/main/tutorials/04-launch-multiple-model.md)？
6. 如何[*结合 LMCache 开启 KV Cache 卸载（Offloading）*](https://github.com/vllm-project/production-stack/blob/main/tutorials/05-offload-kv-cache.md)？

## 系统架构

整个服务栈基于 [Helm](https://helm.sh/docs/) 进行编排部署，包含以下核心组件：

- **推理引擎（Serving engine）**：运行各类不同大语言模型的 vLLM 引擎实例。
- **请求路由器（Request router）**：根据路由键（Routing Keys）或会话 ID（Session ID）将请求精准分发至对应后端节点，以最大化 KV Cache 复用率。
- **可观测性栈（Observability stack）**：通过 [Prometheus](https://github.com/prometheus/prometheus) + [Grafana](https://grafana.com/) 实时监控所有后端实例的运行指标。

<p align="center">
  <img src="https://github.com/user-attachments/assets/8f05e7b9-0513-40a9-9ba9-2d3acca77c0c" alt="Architecture of the stack" width="80%"/>
</p>

## 路线图

我们正在积极推进该项目的研发，并将在近期推出以下核心功能，敬请期待！

- 基于 vLLM 专属指标的**自动扩缩容（Autoscaling）**
- 支持**分离式预填充（Disaggregated Prefill）**
- **路由器全方位增强**（例如：采用非 Python 语言重写的高性能路由器、KV-Cache 感知型路由算法、更完善的容错机制等）

## 通过 Helm 部署服务栈

### 前置条件

- 已运行且配备 GPU 的 Kubernetes（K8s）集群环境
  - 运行 `cd utils && bash install-minikube-cluster.sh`
  - 或参考我们的[环境安装教程](tutorials/00-install-kubernetes-env.md)

### 部署流程

vLLM Production Stack 可直接通过 Helm Charts 部署。将本代码库克隆至本地并执行以下命令即可完成最小化部署：

```bash
git clone https://github.com/vllm-project/production-stack.git
cd production-stack/
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f tutorials/assets/values-01-minimal-example.yaml
```

部署完成的服务栈提供与原生 vLLM 完全一致的 [**OpenAI 兼容 API 接口**](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html?ref=blog.mozilla.ai#openai-compatible-server)，并可通过 Kubernetes Service 直接访问。

如需验证安装结果并向服务栈发送测试查询请求，请参阅[这篇教程](tutorials/01-minimal-helm-installation.md)。

关于如何自定义 Helm Chart 配置的更多信息，请参阅 [values.yaml](https://github.com/vllm-project/production-stack/blob/main/helm/values.yaml) 以及我们的其他[进阶教程](https://github.com/vllm-project/production-stack/tree/main/tutorials)。

### 卸载服务栈

```bash
helm uninstall vllm
```

## Grafana 监控面板

### 功能特性

Grafana 监控面板提供以下核心维度的可观测性洞察：

1. **可用 vLLM 实例数（Available vLLM Instances）**：展示当前处于健康状态的实例数量。
2. **请求延迟分布（Request Latency Distribution）**：可视化端到端请求延迟分布情况。
3. **首 Token 时间（TTFT）分布（Time-to-First-Token Distribution）**：监控首个 Token 生成的响应耗时。
4. **运行中请求数（Number of Running Requests）**：跟踪每个实例当前正在处理的活跃请求数。
5. **排队等待请求数（Number of Pending Requests）**：跟踪正在等待处理的挂起请求数。
6. **GPU KV 显存使用率（GPU KV Usage Percent）**：监控 GPU KV Cache 的容量占用百分比。
7. **GPU KV Cache 命中率（GPU KV Cache Hit Rate）**：展示 GPU KV Cache 的缓存命中率。

<p align="center">
  <img src="https://github.com/user-attachments/assets/05766673-c449-4094-bdc8-dea6ac28cb79" alt="Grafana dashboard to monitor the deployment" width="80%"/>
</p>

### 配置方式

详细配置请参阅 [`helm/README.md`](./helm/README.md#Observability)

## 请求路由器（Router）

路由器负责确保请求在各个后端实例之间实现高效分发，主要支持以下特性：

- 路由至运行不同模型的服务端点
- 导出每个推理引擎实例的可观测性指标，包括 QPS、首 Token 延迟（TTFT）、排队/运行中/已完成请求数量以及运行时长（Uptime）
- 基于 Kubernetes API 的自动服务发现与容错机制
- 模型别名（Model Aliases）映射
- 多种路由算法：
  - 轮询路由（Round-robin routing）
  - 基于会话 ID 路由（Session-ID based routing）
  - 前缀感知路由（Prefix-aware routing，开发中）

更多详细信息请参阅[路由器专项文档](./src/vllm_router/README.md)。

## 参与贡献

我们非常欢迎并珍视任何形式的社区贡献与技术合作。请查阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解如何参与到项目中。

## 开源许可证

本项目基于 Apache License 2.0 许可证开源，详情请参阅 `LICENSE` 文件。

## 赞助商

衷心感谢以下赞助商对本项目研发与基准测试工作的大力支持：

<p align="center">
  <a href="https://gmicloud.ai">
    <img src="https://cdn.prod.website-files.com/6683d8c52e4e62685a8d90cf/67a0a0064683945b0cf77f25_GMI%20Cloud%20Logo_Black.svg" alt="GMI Cloud Logo" width="200"/>
  </a>
</p>

---

如有任何问题或建议，欢迎随时提交 Issue 或直接联系我们（[@ruizhang0101](https://github.com/ruizhang0101)、[@ApostaC](https://github.com/ApostaC)、[@YuhanLiu11](https://github.com/YuhanLiu11)、[@Shaoting-Feng](https://github.com/Shaoting-Feng)）。

*注：本文档由社区志愿者维护（贡献者：[@JasonYeYuhe](https://github.com/JasonYeYuhe)），内容与英文官方文档保持同步（更新时间：2026年10月13日）。如有任何疑问或更新建议，欢迎提交 PR 或 Issue。*
