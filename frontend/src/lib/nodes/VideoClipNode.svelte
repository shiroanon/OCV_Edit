<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { api } from '$lib/api/client';
	import type { VideoClipNodeData } from '$lib/types/plan';

	let { data }: { data: VideoClipNodeData } = $props();

	let thumbSrc = $state<string | null>(null);
	let thumbError = $state(false);

	$effect(() => {
		const fp = data.filepath;
		if (!fp) { thumbSrc = null; thumbError = false; return; }
		let cancelled = false;
		let blobUrl: string | null = null;
		api.thumbnail(fp, (data.startTime || 0) + (data.duration || 0) * 0.25).then((blob) => {
			if (cancelled) return;
			blobUrl = URL.createObjectURL(blob);
			thumbSrc = blobUrl;
		}).catch(() => {
			thumbError = true;
		});
		return () => {
			cancelled = true;
			if (blobUrl) URL.revokeObjectURL(blobUrl);
		};
	});
</script>

<div class="video-clip-node">
	<Handle type="target" position={Position.Left} id="in" />
	<div class="node-header">
		<span class="node-label">{data.label || 'Video Clip'}</span>
	</div>
	<div class="node-thumb">
		{#if thumbSrc}
			<img src={thumbSrc} alt="" class="thumb-img" />
		{:else if thumbError}
			<div class="thumb-placeholder">No preview</div>
		{:else}
			<div class="thumb-placeholder">Loading...</div>
		{/if}
	</div>
	<div class="node-body">
		<div class="field">
			<span class="field-label">File</span>
			<span class="field-value">{data.filepath?.split('/').pop() || '—'}</span>
		</div>
		<div class="field-row">
			<div class="field">
				<span class="field-label">Start</span>
				<span class="field-value">{data.startTime?.toFixed(1) || '0.0'}s</span>
			</div>
			<div class="field">
				<span class="field-label">Dur</span>
				<span class="field-value">{data.duration?.toFixed(1) || '0.0'}s</span>
			</div>
			<div class="field">
				<span class="field-label">Speed</span>
				<span class="field-value">{data.speed?.toFixed(2) || '1.0'}x</span>
			</div>
		</div>
	</div>
	<Handle type="source" position={Position.Right} id="out" />
	<Handle type="source" position={Position.Bottom} id="effect-out" />
</div>

<style>
	.video-clip-node {
		background: #1a1a2e;
		border: 1px solid #4a4a8a;
		border-radius: 8px;
		min-width: 200px;
		font-size: 12px;
		color: #e0e0e0;
	}
	.node-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 10px;
		background: #16213e;
		border-radius: 7px 7px 0 0;
		border-bottom: 1px solid #4a4a8a;
	}
	.node-label { font-weight: 600; font-size: 13px; }
	.node-thumb {
		width: 100%;
		height: 80px;
		overflow: hidden;
		background: #000;
		border-bottom: 1px solid #4a4a8a;
	}
	.thumb-img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.thumb-placeholder {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		color: #555;
		font-size: 11px;
	}
	.node-body { padding: 6px 10px; }
	.field { display: flex; justify-content: space-between; gap: 8px; }
	.field-row { display: flex; gap: 12px; margin-top: 4px; }
	.field-label { color: #888; }
	.field-value { color: #fff; font-family: monospace; }
</style>
