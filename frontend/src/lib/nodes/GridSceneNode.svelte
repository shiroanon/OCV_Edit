<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';

	let { data }: { data: { label: string; layout: [number, number]; gap: number; panelCount: number; duration: number; sceneIndex: number } } = $props();
</script>

<div class="grid-node">
	<Handle type="target" position={Position.Left} id="in" />
	<div class="node-header">
		<span class="node-label">{data.label || 'Grid Scene'}</span>
	</div>
	<div class="node-body">
		<div class="grid-preview" style="grid-template-columns: repeat({data.layout?.[1] || 2}, 1fr)">
			{#each Array(data.panelCount || 1) as _, i}
				<div class="grid-cell">{i + 1}</div>
			{/each}
		</div>
		<div class="field">
			<span class="field-label">Layout</span>
			<span class="field-value">{data.layout?.[0] || 1}×{data.layout?.[1] || 2}</span>
		</div>
		<div class="field">
			<span class="field-label">Dur</span>
			<span class="field-value">{data.duration?.toFixed(1) || '0.0'}s</span>
		</div>
	</div>
	<Handle type="source" position={Position.Right} id="out" />
</div>

<style>
	.grid-node {
		background: #1a2e2e;
		border: 1px solid #4a8a8a;
		border-radius: 8px;
		min-width: 180px;
		font-size: 12px;
		color: #e0e0e0;
	}
	.node-header {
		display: flex;
		align-items: center;
		padding: 6px 10px;
		background: #162e2e;
		border-radius: 7px 7px 0 0;
		border-bottom: 1px solid #4a8a8a;
	}
	.node-label { font-weight: 600; font-size: 13px; }
	.grid-preview {
		display: grid;
		gap: 2px;
		padding: 6px;
		background: #000;
		border-bottom: 1px solid #4a8a8a;
	}
	.grid-cell {
		aspect-ratio: 16 / 9;
		background: #1a3a3a;
		border: 1px solid #4a8a8a;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 10px;
		color: #4a8a8a;
		border-radius: 2px;
	}
	.node-body { padding: 6px 10px; }
	.field { display: flex; justify-content: space-between; gap: 8px; margin-top: 2px; }
	.field-label { color: #888; }
	.field-value { color: #fff; font-family: monospace; }
</style>
