<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import type { EffectNodeData } from '$lib/types/plan';

	let { data }: { data: EffectNodeData } = $props();
</script>

<div class="effect-node">
	<Handle type="target" position={Position.Left} id="in" />
	<div class="node-header">
		<span class="node-label">{data.label || 'Effect'}</span>
	</div>
	<div class="node-body">
		<div class="field">
			<span class="field-label">Type</span>
			<span class="field-value type-badge">{data.effectType || 'ZoomEffect'}</span>
		</div>
		{#if data.params?.easing}
			<div class="field">
				<span class="field-label">Easing</span>
				<span class="field-value">{data.params.easing}</span>
			</div>
		{/if}
		{#each Object.entries(data.params || {}) as [key, val]}
			{#if key !== 'easing'}
				<div class="field">
					<span class="field-label">{key}</span>
					<span class="field-value">{String(val)}</span>
				</div>
			{/if}
		{/each}
	</div>
</div>

<style>
	.effect-node {
		background: #2e1a2e;
		border: 1px solid #8a4a8a;
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
		background: #2e162e;
		border-radius: 7px 7px 0 0;
		border-bottom: 1px solid #8a4a8a;
	}
	.node-label { font-weight: 600; font-size: 13px; }
	.node-body { padding: 8px 12px; max-height: 200px; overflow-y: auto; }
	.field { display: flex; justify-content: space-between; gap: 8px; margin-top: 2px; }
	.field-label { color: #888; white-space: nowrap; }
	.field-value { color: #fff; font-family: monospace; font-size: 11px; text-align: right; }
	.type-badge {
		background: #6a1b9a;
		color: #ce93d8;
		padding: 0 6px;
		border-radius: 3px;
	}
</style>
