# CDN Proxy 部署指南 (K3s Kubernetes)

本项目提供了一个在 K3s 集群中运行的内部 Nginx CDN 缓存代理服务，部署在 `namespace: proxy` 下。

## 1. 架构与三层下载结构

1. **Tier 1 (Nginx 内网缓存代理)**:
   - 内部服务地址：`http://cdn-proxy.proxy.svc.cluster.local/{oss_bucket}/{signed_path}`
   - **命名原则：路径第一段 = OSS bucket 名，bucket 与 CDN 一一对应。**
   - 缓存策略：`inactive=7d`（7天未被访问/touch 的文件由 Nginx 缓存管理器自动删除，避免撑爆磁盘），`max_size=200g`。
   - 鉴权归一化：动态 Type-B 签名 URL 会自动剥离鉴权前缀，统一使用规范对象路径作为 Cache Key，确保不同时刻签名的相同文件命中同一份本地磁盘缓存。
   - 仅缓存 HTTP 200 完整文件，杜绝 206 Range 分片污染，由 Nginx 内部切片模块提供本地分片支持。
2. **Tier 2 (公网 CDN 回源)**:
   - 缓存未命中或过期时，Nginx 自动透传请求至对应阿里云公网 CDN，并带 `proxy_cache_lock on` 防击穿。
   - 开启上游 TLS 证书及受信任 CA 严格校验，防止 DNS 劫持与 MITM 攻击。
   - bucket → CDN：
     - `/ivypri/` -> `https://private.cdn.ivysci.com`
     - `/ivypri-testing/` -> `https://private-testing.cdn.ivysci.com`
     - `/ivypub/` -> `https://public.cdn.ivysci.com`
     - `/ivypub-testing/` -> `https://public-testing.cdn.ivysci.com`
     - `/ivyasset/` -> `https://asset.cdn.ivysci.com`
     - `/ivyscholardata/` -> `https://scholardata.cdn.ivysci.com`
     - `/ivyscholardata-testing/` -> `https://scholardata-testing.cdn.ivysci.com`
   - 待下线别名（rewrite 到上表，随后删除）：`/default/` `/private/` → `/ivypri/`，`/default-testing/` `/private-testing/` → `/ivypri-testing/`，以及 `/public/` `/asset/` `/scholardata/` 的对应关系。
3. **Tier 3 (OSS SDK 直接降级)**:
   - `ivysci_object_reader` 在遇到网络异常或 5xx 故障时，自动回退调用 Aliyun OSS SDK 直接下载。

---

## 2. 节点双机房调度与标签配置 (Home vs Office)

集群节点机房标签配置命令：
```bash
# 1. Office 机房节点
kubectl label node ivysci-black topology.kubernetes.io/zone=office cdn-proxy=true --overwrite

# 2. Home 机房节点
kubectl label node ivysci-black2 topology.kubernetes.io/zone=home cdn-proxy=true --overwrite
```

StatefulSet 配置了基于 `topology.kubernetes.io/zone` 的拓扑分布约束（`topologySpreadConstraints`）与强反亲和性（`podAntiAffinity`），**保证 2 个 Pod 严格分别调度到 `ivysci-black` (office) 和 `ivysci-black2` (home)**，两台机器各自拥有独立的 200Gi 本地 PVC 缓存。

### Service 同机房优先路由

Service 使用 Kubernetes 原生的 `trafficDistribution: PreferClose`：

```yaml
spec:
  trafficDistribution: PreferClose
```

- 正常情况下，office 发出的请求优先路由到 office 代理，home 发出的请求优先路由到 home 代理，避免 PDF 等大文件跨机房传输。
- 本机房代理不可用时，允许降级到另一机房的健康代理，以可用性优先；这不是严格的机房隔离策略。
- **不要同时配置旧的 `service.kubernetes.io/topology-mode: Auto` annotation。** 该 annotation 的优先级高于 `trafficDistribution`，会覆盖 `PreferClose`。旧的 Auto 启发式在每个机房只有少量端点（本部署每个机房只有 1 个）时可能不生成 EndpointSlice hints，最终退回集群全局随机路由，重新产生跨机房流量。

部署后必须检查 EndpointSlice hints，而不能只检查 Service 字段：

```bash
kubectl get endpointslice -n proxy \
  -l kubernetes.io/service-name=cdn-proxy \
  -o jsonpath='{range .items[*].endpoints[*]}{.targetRef.name}{" zone="}{.zone}{" hints="}{.hints.forZones[*].name}{"\n"}{end}'
```

正确结果应类似：

```text
cdn-proxy-1 zone=office hints=office
cdn-proxy-0 zone=home hints=home
```

---

## 3. 一键部署与验证

### 部署到集群
```bash
# 使用 kubectl kustomize 部署
kubectl apply -k .k8s/
```

### 查看状态
```bash
# 检查 Pod 运行状态及分布节点 (应分别运行在 ivysci-black 和 ivysci-black2 上)
kubectl get pod -n proxy -o wide

# 检查 2 个独立的 PVC 绑定状态 (cache-cdn-proxy-0, cache-cdn-proxy-1)
kubectl get pvc -n proxy

# 检查 Service 的同机房优先配置
kubectl get svc cdn-proxy -n proxy -o jsonpath='trafficDistribution={.spec.trafficDistribution}{"\n"}'

# 检查每个代理端点的机房及路由 hints
kubectl get endpointslice -n proxy \
  -l kubernetes.io/service-name=cdn-proxy \
  -o jsonpath='{range .items[*].endpoints[*]}{.targetRef.name}{" zone="}{.zone}{" hints="}{.hints.forZones[*].name}{"\n"}{end}'
```

### 调试与测试
```bash
# 查看 Nginx 访问与缓存命中日志 (实时标准输出 stream，包含 cache=HIT/MISS)
kubectl logs -n proxy -l app=cdn-proxy -c nginx -f

# 集群内部测试健康检查
kubectl run curl-test --image=curlimages/curl --rm -it --restart=Never -n proxy -- curl -I http://cdn-proxy/healthz
```
