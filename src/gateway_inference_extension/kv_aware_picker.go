package picker

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"sigs.k8s.io/gateway-api-inference-extension/pkg/epp/scheduling/plugins"
	"sigs.k8s.io/gateway-api-inference-extension/pkg/epp/scheduling/types"
	logutil "sigs.k8s.io/gateway-api-inference-extension/pkg/epp/util/logging"
)

// KvAwarePicker attempts to route requests to the pod that already holds
// the longest matching KV cache. If no information is available it falls
// back to a round robin selection.
//
// NOTE: The actual lookup against the LMCache controller is left as a TODO
// as the Go library for LMCache is not yet available. The code structure
// mirrors the Python implementation found in routing_logic.KvawareRouter.
var _ plugins.Picker = &KvAwarePicker{}

type KvAwarePicker struct {
	currentIndex   uint64
	controllerAddr string
	threshold      int
	instToPod      map[string]*types.ScoredPod
	httpClient     *http.Client
}

func NewKvAwarePicker(addr string, threshold int) *KvAwarePicker {
	return &KvAwarePicker{
		controllerAddr: addr,
		threshold:      threshold,
		instToPod:      make(map[string]*types.ScoredPod),
		httpClient:     &http.Client{Timeout: 2 * time.Second},
	}
}

func (p *KvAwarePicker) Name() string { return "kvaware" }

func (p *KvAwarePicker) Pick(ctx *types.SchedulingContext, scoredPods []*types.ScoredPod) *types.Result {
	if len(scoredPods) == 0 {
		return &types.Result{}
	}

	prompt := ctx.Request.Prompt
	model := ctx.Request.Model

	inst, tokens, err := p.lookupInstance(model, prompt)
	if err == nil && inst != "" {
		if tokens >= len(strings.Fields(prompt))-p.threshold {
			if _, ok := p.instToPod[inst]; !ok {
				for _, pod := range scoredPods {
					ip := pod.GetPod().Status.PodIP
					iid, err := p.queryInstance(ip)
					if err == nil && iid != "" {
						p.instToPod[iid] = pod
					}
				}
			}
			if target, ok := p.instToPod[inst]; ok {
				ctx.Logger.V(logutil.DEBUG).Info(fmt.Sprintf("KvAwarePicker routed to %s", inst))
				return &types.Result{TargetPod: target}
			}
		}
	}

	// Fallback to round robin routing when no KV cache information is
	// available. Sort candidates for deterministic behavior across schedulers.
	sort.Slice(scoredPods, func(i, j int) bool {
		return scoredPods[i].GetPod().NamespacedName.String() <
			scoredPods[j].GetPod().NamespacedName.String()
	})
	index := int(atomic.AddUint64(&p.currentIndex, 1) - 1)
	index = index % len(scoredPods)
	ctx.Logger.V(logutil.DEBUG).Info(fmt.Sprintf(
		"KvAwarePicker falling back to round robin, index %d of %d", index, len(scoredPods)))
	return &types.Result{TargetPod: scoredPods[index]}
}

// lookupInstance queries the LMCache controller for the instance containing the
// longest prefix match for the given prompt. It returns the instance ID and the
// number of matched tokens.
func (p *KvAwarePicker) lookupInstance(model, prompt string) (string, int, error) {
	body, err := json.Marshal(map[string]string{"model": model, "prompt": prompt})
	if err != nil {
		return "", 0, err
	}
	url := fmt.Sprintf("http://%s/lookup", p.controllerAddr)
	resp, err := p.httpClient.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", 0, fmt.Errorf("unexpected status %d", resp.StatusCode)
	}
	var data struct {
		InstanceID string `json:"instance_id"`
		Tokens     int    `json:"tokens"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return "", 0, err
	}
	return data.InstanceID, data.Tokens, nil
}

// queryInstance resolves the instance ID for the given pod IP. It returns an
// empty string if the controller does not recognize the pod.
func (p *KvAwarePicker) queryInstance(ip string) (string, error) {
	url := fmt.Sprintf("http://%s/query?ip=%s", p.controllerAddr, ip)
	resp, err := p.httpClient.Get(url)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("unexpected status %d", resp.StatusCode)
	}
	var data struct {
		InstanceID string `json:"instance_id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return "", err
	}
	return data.InstanceID, nil
}
