<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';

	let { data }: { data: { label: string; fps: number; outputSize: [number, number]; resizeMode: string } } = $props();
</script>

<div class="init-node">
	<div class="node-header">
		<span class="node-label">{data.label || 'Scene Init'}</span>
	</div>
	<div class="node-body">
		<div class="field">
			<span class="field-label">Output</span>
			<span class="field-value">{data.outputSize?.[0] || 1920}×{data.outputSize?.[1] || 1080}</span>
		</div>
		<div class="field">
			<span class="field-label">FPS</span>
			<span class="field-value">{data.fps || 30}</span>
		</div>
		<div class="field">
			<span class="field-label">Resize</span>
			<span class="field-value">{data.resizeMode || 'fill'}</span>
		</div>
	</div>
</div>

<style>
	.init-node {
		background: #1a1a2e;
		border: 2px solid #6a4aff;
		border-radius: 8px;
		min-width: 160px;
		font-size: 12px;
		color: #e0e0e0;
	}
	.node-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 10px;
		background: #2a1a5e;
		border-radius: 6px 6px 0 0;
		border-bottom: 1px solid #6a4aff;
	}
	.node-label { font-weight: 600; font-size: 13px; color: #b388ff; }
	.node-body { padding: 6px 10px; }
	.field { display: flex; justify-content: space-between; gap: 8px; margin-top: 2px; }
	.field-label { color: #888; }
	.field-value { color: #fff; font-family: monospace; }
</style>
