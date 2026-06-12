<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import type { TransitionNodeData } from '$lib/types/plan';

	let { data }: { data: TransitionNodeData } = $props();
</script>

<div class="transition-node">
	<Handle type="target" position={Position.Left} id="in" />
	<div class="node-header">
		<span class="node-label">{data.label || 'Transition'}</span>
	</div>
	<div class="node-body">
		<div class="field">
			<span class="field-label">Type</span>
			<span class="field-value type-badge">{data.transitionType || 'slide'}</span>
		</div>
		<div class="field">
			<span class="field-label">Duration</span>
			<span class="field-value">{data.duration?.toFixed(2) || '0.20'}s</span>
		</div>
		{#if data.direction}
			<div class="field">
				<span class="field-label">Direction</span>
				<span class="field-value">{data.direction}</span>
			</div>
		{/if}
		{#if data.mode}
			<div class="field">
				<span class="field-label">Mode</span>
				<span class="field-value">{data.mode}</span>
			</div>
		{/if}
	</div>
	<Handle type="source" position={Position.Right} id="out" />
</div>

<style>
	.transition-node {
		background: #1a2e1a;
		border: 1px solid #4a8a4a;
		border-radius: 8px;
		min-width: 180px;
		font-size: 12px;
		color: #e0e0e0;
	}
	.node-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		background: #162e16;
		border-radius: 7px 7px 0 0;
		border-bottom: 1px solid #4a8a4a;
	}
	.node-label { font-weight: 600; font-size: 13px; }
	.node-body { padding: 8px 12px; }
	.field { display: flex; justify-content: space-between; gap: 8px; margin-top: 2px; }
	.field-label { color: #888; }
	.field-value { color: #fff; font-family: monospace; }
	.type-badge {
		background: #1b5e20;
		color: #a5d6a7;
		padding: 0 6px;
		border-radius: 3px;
	}
</style>
