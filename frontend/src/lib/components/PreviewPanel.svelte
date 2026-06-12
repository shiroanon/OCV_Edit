<script lang="ts">
	import { currentPlan, previewTime, isPlaying, totalDuration } from '$lib/stores/plan';
	import { api } from '$lib/api/client';

	let frameSrc = $state<string | null>(null);
	let segmentSrc = $state<string | null>(null);
	let isLoading = $state(false);
	let loadingLabel = $state('');
	let error = $state<string | null>(null);
	let videoRef: HTMLVideoElement | undefined = $state();
	let seekTimeout: ReturnType<typeof setTimeout> | undefined;
	let playInterval: ReturnType<typeof setInterval> | undefined;
	let currentBlobUrl: string | null = null;
	let minLoadingTimer: ReturnType<typeof setTimeout> | undefined;
	let showLoading = $state(false);
	let maxTime = $state(60);
	let curTime = $state(0);
	let playing = $state(false);

	function revokeUrl(url: string | null) {
		if (url && url.startsWith('blob:')) {
			URL.revokeObjectURL(url);
		}
	}

	async function fetchFrame(time: number) {
		let plan: import('$lib/types/plan').EditPlan;
		const unsub = currentPlan.subscribe((p) => (plan = p))();
		if (!plan || plan.scenes.length === 0) {
			unsub();
			return;
		}
		unsub();

		clearTimeout(minLoadingTimer);
		isLoading = true;
		showLoading = true;
		loadingLabel = 'Seeking frame...';
		error = null;
		const start = performance.now();
		try {
			const blob = await api.previewFrame(plan, time);
			revokeUrl(currentBlobUrl);
			const url = URL.createObjectURL(blob);
			currentBlobUrl = url;
			frameSrc = url;
		} catch (e) {
			error = String(e);
		} finally {
			const elapsed = performance.now() - start;
			const remaining = Math.max(0, 300 - elapsed);
			minLoadingTimer = setTimeout(() => { isLoading = false; showLoading = false; }, remaining);
		}
	}

	function onSeek(event: Event) {
		const t = parseFloat((event.target as HTMLInputElement).value);
		previewTime.set(t);
		clearTimeout(seekTimeout);
		seekTimeout = setTimeout(() => fetchFrame(t), 100);
	}

	function playSegment() {
		let plan: import('$lib/types/plan').EditPlan;
		let time = 0;
		let total = 60;
		const unsub1 = currentPlan.subscribe((p) => (plan = p))();
		const unsub2 = previewTime.subscribe((t) => (time = t))();
		const unsub3 = totalDuration.subscribe((d) => (total = d))();
		isPlaying.set(true);
		clearTimeout(minLoadingTimer);
		isLoading = true;
		showLoading = true;
		loadingLabel = 'Rendering segment...';
		const start = performance.now();

		const dur = Math.max(0.5, total - time);
		api.previewSegment({ plan, start_time: time, duration: dur })
			.then((blob) => {
				revokeUrl(currentBlobUrl);
				const url = URL.createObjectURL(blob);
				currentBlobUrl = url;
				segmentSrc = url;
				if (videoRef) {
					videoRef.src = url;
					videoRef.play();
				}
			})
			.catch((e) => (error = String(e)))
			.finally(() => {
				const elapsed = performance.now() - start;
				const remaining = Math.max(0, 300 - elapsed);
				minLoadingTimer = setTimeout(() => { isLoading = false; showLoading = false; }, remaining);
				unsub1();
				unsub2();
				unsub3();
			});
	}

	function stopPlayback() {
		isPlaying.set(false);
		if (videoRef) {
			videoRef.pause();
			videoRef.currentTime = 0;
		}
		segmentSrc = null;
	}

	function onVideoEnded() {
		stopPlayback();
	}

	$effect(() => {
		const us1 = totalDuration.subscribe((v) => { maxTime = v; });
		const us2 = previewTime.subscribe((v) => { curTime = v; });
		const us3 = isPlaying.subscribe((v) => { playing = v; });
		return () => { us1(); us2(); us3(); };
	});

	$effect(() => {
		if (!playing) {
			clearTimeout(seekTimeout);
			seekTimeout = setTimeout(() => fetchFrame(curTime), 150);
		}
		return () => {
			clearTimeout(seekTimeout);
			clearInterval(playInterval);
			clearTimeout(minLoadingTimer);
			revokeUrl(currentBlobUrl);
		};
	});
</script>

<div class="preview-panel">
	<div class="preview-header">
		<h3>Preview</h3>
		<div class="preview-controls">
			<button
				class="btn"
				onclick={playSegment}
				disabled={isLoading}
			>
				▶ Play
			</button>
			<button class="btn" onclick={stopPlayback}>
				⏹ Stop
			</button>
		</div>
	</div>

	<div class="preview-viewport">
		{#if segmentSrc}
			<video
				bind:this={videoRef}
				src={segmentSrc}
				onended={onVideoEnded}
				controls
				autoplay
				class="preview-video"
			></video>
		{:else if frameSrc}
			<img src={frameSrc} alt="Preview frame" class="preview-image" />
		{:else}
			<div class="placeholder">
				<p>No preview</p>
				<p class="hint">Add clips and seek the timeline</p>
			</div>
		{/if}
		{#if showLoading}
			<div class="loading-overlay">
				<div class="loading-bar"><div class="loading-bar-fill"></div></div>
				<div class="loading-label">{loadingLabel}</div>
			</div>
		{/if}
	</div>

	<div class="timeline-row">
		<span class="time-label">{curTime.toFixed(1)}s</span>
		<input
			type="range"
			class="timeline-slider"
			min="0"
			max={maxTime}
			step="0.05"
			value={curTime}
			oninput={onSeek}
		/>
		<span class="time-label">{maxTime.toFixed(1)}s</span>
	</div>

	{#if error}
		<div class="error-banner">{error}</div>
	{/if}
</div>

<style>
	.preview-panel {
		background: #111;
		border-left: 1px solid #333;
		display: flex;
		flex-direction: column;
		height: 100%;
	}
	.preview-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-bottom: 1px solid #333;
	}
	.preview-header h3 {
		margin: 0;
		font-size: 14px;
		color: #ccc;
	}
	.preview-controls { display: flex; gap: 4px; }
	.btn {
		background: #333;
		color: #fff;
		border: 1px solid #555;
		padding: 4px 10px;
		border-radius: 4px;
		cursor: pointer;
		font-size: 12px;
	}
	.btn:disabled { opacity: 0.5; cursor: default; }
	.preview-viewport {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		position: relative;
		background: #000;
		min-height: 200px;
		overflow: hidden;
	}
	.preview-image, .preview-video {
		max-width: 100%;
		max-height: 100%;
		object-fit: contain;
	}
	.placeholder {
		color: #555;
		text-align: center;
	}
	.placeholder .hint { font-size: 11px; margin-top: 4px; }
	.loading-bar {
		position: absolute;
		bottom: 0;
		left: 0;
		right: 0;
		height: 3px;
		background: #333;
		overflow: hidden;
	}
	.loading-bar-fill {
		height: 100%;
		width: 30%;
		background: #6a4aff;
		animation: loading-slide 1.2s ease-in-out infinite;
	}
	@keyframes loading-slide {
		0% { transform: translateX(-100%); }
		100% { transform: translateX(400%); }
	}
	.loading-overlay {
		position: absolute;
		inset: 0;
		z-index: 10;
		pointer-events: none;
	}
	.loading-label {
		position: absolute;
		bottom: 8px;
		left: 50%;
		transform: translateX(-50%);
		font-size: 11px;
		color: #aaa;
		background: rgba(0,0,0,0.6);
		padding: 2px 8px;
		border-radius: 3px;
		z-index: 11;
	}
	.timeline-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 12px;
	}
	.time-label {
		font-size: 11px;
		color: #666;
		font-family: monospace;
		min-width: 36px;
		text-align: center;
	}
	.timeline-slider {
		flex: 1;
		accent-color: #6a4aff;
		height: 8px;
		cursor: pointer;
	}
	.error-banner {
		padding: 6px 12px;
		background: #3e1212;
		color: #ff6b6b;
		font-size: 11px;
		font-family: monospace;
		word-break: break-all;
	}
</style>
