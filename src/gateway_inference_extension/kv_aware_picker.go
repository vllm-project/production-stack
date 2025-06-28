package picker

import (
	"fmt"
	"sort"
	"sync/atomic"

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
}

func NewKvAwarePicker(addr string, threshold int) *KvAwarePicker {
	return &KvAwarePicker{controllerAddr: addr, threshold: threshold}
}

func (p *KvAwarePicker) Name() string { return "kvaware" }

// Pick selects a pod based on KV cache information when possible.
// The current implementation falls back to a round robin policy and
// leaves the LMCache lookup as future work.
func (p *KvAwarePicker) Pick(ctx *types.SchedulingContext, scoredPods []*types.ScoredPod) *types.Result {
	if len(scoredPods) == 0 {
		return &types.Result{}
	}

	// TODO: implement LMCache lookup to find the instance id with the
	// longest prefix match for the prompt in ctx.Request.Prompt.
	// This should then map the instance id back to one of the scoredPods.

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
