<script lang="ts">
	import { currentPlan, selectedSceneIndex, selectedClipIndex, planSettingsSelected } from '$lib/stores/plan';
	import { updateScene, updateClip, removeClip, removeScene, setTransition, updatePlanSettings, addGridScene } from '$lib/stores/plan';
	import { api } from '$lib/api/client';
	import EasingEditor from '$lib/components/EasingEditor.svelte';
	import type { SceneData, ClipData, TransitionType, FileEntry, EditPlan, EffectEntry } from '$lib/types/plan';

	let plan = $state<EditPlan>({ output_size: [1920, 1080], fps: 30, resize_mode: 'fill', global_effects: [], scenes: [] });
	let videoFiles = $state<FileEntry[]>([]);
	let selSceneIdx = $state<number | null>(null);
	let selClipIdx = $state<number | null>(null);
	let selPlanSettings = $state(false);
	let selectedEffectIndex = $state<number | null>(null);
	let unsub: (() => void) | undefined;

	$effect(() => {
		unsub = currentPlan.subscribe((p) => (plan = p));
		return () => unsub?.();
	});

	$effect(() => {
		const us1 = selectedSceneIndex.subscribe((v) => (selSceneIdx = v));
		const us2 = selectedClipIndex.subscribe((v) => (selClipIdx = v));
		const us3 = planSettingsSelected.subscribe((v) => (selPlanSettings = v));
		return () => { us1(); us2(); us3(); };
	});

	$effect(() => {
		api.videos().then((v) => { videoFiles = v; }).catch(() => { videoFiles = []; });
	});

	let currentScene = $derived(
		selSceneIdx !== null ? plan.scenes[selSceneIdx] ?? null : null
	);
	let currentClip = $derived<ClipData | null>(
		selSceneIdx !== null && selClipIdx !== null
			? plan.scenes[selSceneIdx]?.clips[selClipIdx] ?? null
			: null
	);

	function handleSceneChange(field: string, value: unknown) {
		if (selSceneIdx === null) return;
		const updated = updateScene(plan, selSceneIdx, { [field]: value });
		currentPlan.set(updated);
	}

	function handleClipChange(field: string, value: unknown) {
		if (selSceneIdx === null || selClipIdx === null) return;
		const updated = updateClip(plan, selSceneIdx, selClipIdx, { [field]: value });
		currentPlan.set(updated);
	}

	function handleEffectChange(field: string, value: unknown) {
		if (selSceneIdx === null || selClipIdx === null || selectedEffectIndex === null) return;
		const clip = plan.scenes[selSceneIdx]?.clips[selClipIdx];
		if (!clip) return;
		const effects = clip.effects.map((e, i) =>
			i === selectedEffectIndex ? { ...e, [field]: value } : e
		);
		handleClipChange('effects', effects);
	}

	function handleEffectParamsChange(params: Record<string, unknown>) {
		if (selSceneIdx === null || selClipIdx === null || selectedEffectIndex === null) return;
		const clip = plan.scenes[selSceneIdx]?.clips[selClipIdx];
		if (!clip || !clip.effects[selectedEffectIndex]) return;
		const effects = clip.effects.map((e, i) =>
			i === selectedEffectIndex ? { ...e, params: { ...e.params, ...params } } : e
		);
		handleClipChange('effects', effects);
	}

	function handleDeleteClip() {
		if (selSceneIdx === null || selClipIdx === null) return;
		const updated = removeClip(plan, selSceneIdx, selClipIdx);
		currentPlan.set(updated);
		selectedClipIndex.set(null);
	}

	function handleDeleteScene() {
		if (selSceneIdx === null) return;
		const updated = removeScene(plan, selSceneIdx);
		currentPlan.set(updated);
		selectedSceneIndex.set(null);
	}

	function handleTransitionType(type: string) {
		if (selSceneIdx === null) return;
		const scene = plan.scenes[selSceneIdx];
		const updated = setTransition(plan, selSceneIdx, {
			type: type as TransitionType,
			duration: scene.transition?.duration ?? 0.2,
			params: scene.transition?.params ?? {}
		});
		currentPlan.set(updated);
	}

	function handlePlanSetting(field: string, value: unknown) {
		const updated = updatePlanSettings(plan, { [field]: value });
		currentPlan.set(updated);
	}

	function handleAddGridScene() {
		const fp = videoFiles[0]?.path || 'videos/1.mp4';
		const updated = addGridScene(plan, 2, 2, fp);
		currentPlan.set(updated);
	}

	function handlePanelFile(panelIdx: number, filepath: string) {
		if (selSceneIdx === null || !currentScene?.clips[0]?.panels) return;
		const panels = [...currentScene.clips[0].panels];
		panels[panelIdx] = { ...panels[panelIdx], file: filepath };
		handleClipChange('panels', panels);
	}

	function handleAddPanelToScene() {
		if (selSceneIdx === null) return;
		const scene = plan.scenes[selSceneIdx];
		const clip = scene.clips[0];
		const panels = [...(clip.panels || [])];
		const fp = videoFiles[0]?.path || clip.filepath || 'videos/1.mp4';
		panels.push({ file: fp, start_time: 0, speed: 1, effects: [] });
		handleClipChange('panels', panels);
	}

	const transitionTypes = ['slide', 'zoom', 'grid_wipe', 'flash', 'radial_wipe', 'zoom_in'];

	const NUMBER_PARAMS = ['start_zoom', 'end_zoom', 'start_blur', 'end_blur', 'start_shift', 'end_shift', 'intensity', 'pulse_speed', 'pulse_amplitude', 'font_size', 'opacity', 'start_scale', 'end_scale', 'pulse_scale', 'max_angle', 'amplitude', 'start_offset', 'end_offset', 'bar_speed', 'bar_width', 'num_bars', 'frequency', 'speed', 'max_pixels', 'min_pixels', 'zoom_out', 'zoom_in', 'drift_x', 'drift_y', 'inner_radius', 'outer_radius', 'flash_point', 'max_zoom', 'blur_peak'];
	const COLOR_PARAMS = ['color', 'inner_color', 'outer_color'];
	const TEXT_PARAMS = ['text', 'position', 'direction', 'mode', 'stagger', 'origin'];
	const BOOL_PARAMS: string[] = [];
</script>

<aside class="properties-panel">
	<h3>Properties</h3>

	{#if selPlanSettings}
		<section class="section">
			<h4>Plan Settings</h4>
			<label class="field-row">
				<span>Output Width</span>
				<input
					type="number"
					value={plan.output_size[0]}
					oninput={(e) => handlePlanSetting('output_size', [parseInt(e.currentTarget.value) || 1920, plan.output_size[1]])}
					step="10"
					min="1"
				/>
			</label>
			<label class="field-row">
				<span>Output Height</span>
				<input
					type="number"
					value={plan.output_size[1]}
					oninput={(e) => handlePlanSetting('output_size', [plan.output_size[0], parseInt(e.currentTarget.value) || 1080])}
					step="10"
					min="1"
				/>
			</label>
			<label class="field-row">
				<span>FPS</span>
				<input
					type="number"
					value={plan.fps}
					oninput={(e) => handlePlanSetting('fps', parseFloat(e.currentTarget.value) || 30)}
					step="1"
					min="1"
				/>
			</label>
			<label class="field-row">
				<span>Resize Mode</span>
				<select
					value={plan.resize_mode}
					onchange={(e) => handlePlanSetting('resize_mode', e.currentTarget.value)}
				>
					<option value="fill">fill</option>
					<option value="fit">fit</option>
					<option value="stretch">stretch</option>
				</select>
			</label>
			<label class="field-row">
				<span>Audio File</span>
				<input
					type="text"
					value={plan.audio_path || ''}
					oninput={(e) => handlePlanSetting('audio_path', e.currentTarget.value || undefined)}
					placeholder="None"
				/>
			</label>
		</section>
	{/if}

	{#if currentScene}
		<section class="section">
			<h4>Scene {selSceneIdx}</h4>
			{#if currentScene.is_grid}
				<div class="grid-info">
					<span>Grid Scene</span>
					<button class="btn sm" onclick={handleAddPanelToScene}>+ Panel</button>
				</div>
				{#if currentScene.clips[0]?.panels}
					{#each currentScene.clips[0].panels as panel, pi}
						<div class="panel-row">
							<span class="panel-label">P{pi}</span>
							<select
								value={panel.file || ''}
								onchange={(e) => handlePanelFile(pi, e.currentTarget.value)}
							>
								{#if videoFiles.length === 0}
									<option value={panel.file}>{panel.file || 'None'}</option>
								{:else}
									{#each videoFiles as vf}
										<option value={vf.path}>{vf.name}</option>
									{/each}
								{/if}
							</select>
						</div>
					{/each}
				{/if}
			{:else}
				<label class="field-row">
					<span>Duration</span>
					<input
						type="number"
						value={currentScene.out_dur}
						oninput={(e) => handleSceneChange('out_dur', parseFloat(e.currentTarget.value) || 0)}
						step="0.1"
						min="0.1"
					/>
				</label>
				<label class="field-row">
					<span>Video File</span>
					<input
						type="text"
						value={currentScene.video_file}
						oninput={(e) => handleSceneChange('video_file', e.currentTarget.value)}
					/>
				</label>

				<div class="section">
					<h5>Transition</h5>
					<select
						value={currentScene.transition?.type ?? ''}
						onchange={(e) => {
							const val = e.currentTarget.value;
							if (val) handleTransitionType(val);
						}}
					>
						<option value="">None</option>
						{#each transitionTypes as tt}
							<option value={tt}>{tt}</option>
						{/each}
					</select>
					{#if currentScene.transition}
						<label class="field-row">
							<span>Trans Dur</span>
							<input
								type="number"
								value={currentScene.transition.duration}
								oninput={(e) => {
									if (selSceneIdx === null) return;
									const dur = parseFloat(e.currentTarget.value) || 0.1;
									const updated = setTransition(plan, selSceneIdx, {
										...currentScene.transition!,
										duration: dur
									});
									currentPlan.set(updated);
								}}
								step="0.05"
								min="0.05"
							/>
						</label>
					{/if}
				</div>
			{/if}

			<button class="btn danger" onclick={handleDeleteScene}>Remove Scene</button>
		</section>
	{/if}

	{#if currentClip}
		<section class="section">
			<h4>Clip {selSceneIdx}.{selClipIdx}</h4>
			<label class="field-row">
				<span>File</span>
				<select
					value={currentClip.filepath}
					onchange={(e) => handleClipChange('filepath', e.currentTarget.value)}
				>
					{#if videoFiles.length === 0}
						<option value={currentClip.filepath}>{currentClip.filepath}</option>
					{:else}
						{#each videoFiles as vf}
							<option value={vf.path}>{vf.name}</option>
						{/each}
					{/if}
				</select>
			</label>
			<label class="field-row">
				<span>Start</span>
				<input
					type="number"
					value={currentClip.start_time}
					oninput={(e) => handleClipChange('start_time', parseFloat(e.currentTarget.value) || 0)}
					step="0.1"
					min="0"
				/>
			</label>
			<label class="field-row">
				<span>Duration</span>
				<input
					type="number"
					value={currentClip.duration}
					oninput={(e) => handleClipChange('duration', parseFloat(e.currentTarget.value) || 0.1)}
					step="0.1"
					min="0.1"
				/>
			</label>
			<label class="field-row">
				<span>Speed</span>
				<input
					type="number"
					value={currentClip.speed}
					oninput={(e) => handleClipChange('speed', parseFloat(e.currentTarget.value) || 1)}
					step="0.1"
					min="0.1"
				/>
			</label>
			<button class="btn danger" onclick={handleDeleteClip}>Remove Clip</button>
		</section>
	{/if}

	{#if currentClip && currentClip.effects.length > 0}
		<section class="section">
			<h4>Effects</h4>
			{#each currentClip.effects as effect, ei}
				<div
					class="effect-entry"
					class:active={selectedEffectIndex === ei}
					onclick={() => selectedEffectIndex = ei}
					onkeydown={(e) => { if (e.key === 'Enter') selectedEffectIndex = ei; }}
					role="button"
					tabindex="0"
				>
					<span class="effect-label">{effect.type}</span>
					<span class="effect-time">{effect.start_time}s - {effect.duration}s</span>
				</div>
				{#if selectedEffectIndex === ei}
					<div class="effect-params">
						<label class="field-row">
							<span>Start</span>
							<input
								type="number"
								value={effect.start_time}
								oninput={(e) => handleEffectChange('start_time', parseFloat(e.currentTarget.value) || 0)}
								step="0.05"
								min="0"
							/>
						</label>
						<label class="field-row">
							<span>Duration</span>
							<input
								type="number"
								value={effect.duration}
								oninput={(e) => handleEffectChange('duration', parseFloat(e.currentTarget.value) || 0.05)}
								step="0.05"
								min="0.05"
							/>
						</label>
						{#each Object.entries(effect.params || {}) as [key, val]}
							{#if key === 'easing'}
								<div class="easing-section">
									<span class="param-label">{key}</span>
									<EasingEditor
										value={val as string}
										onChange={(v) => handleEffectParamsChange({ [key]: v })}
									/>
								</div>
							{:else if NUMBER_PARAMS.includes(key)}
								<label class="field-row">
									<span>{key}</span>
									<input
										type="number"
										value={val as number}
										oninput={(e) => handleEffectParamsChange({ [key]: parseFloat(e.currentTarget.value) || 0 })}
										step="0.05"
									/>
								</label>
							{:else if TEXT_PARAMS.includes(key)}
								<label class="field-row">
									<span>{key}</span>
									<input
										type="text"
										value={val as string}
										oninput={(e) => handleEffectParamsChange({ [key]: e.currentTarget.value })}
									/>
								</label>
							{:else}
								<label class="field-row">
									<span>{key}</span>
									<input
										type="text"
										value={String(val)}
										oninput={(e) => handleEffectParamsChange({ [key]: e.currentTarget.value })}
									/>
								</label>
							{/if}
						{/each}
					</div>
				{/if}
			{/each}
		</section>
	{/if}

	{#if !currentScene && !currentClip && !selPlanSettings}
		<p class="no-selection">Select a node in the graph to edit its properties</p>
	{/if}
</aside>

<style>
	.properties-panel {
		width: 280px;
		background: #1a1a1a;
		border-left: 1px solid #333;
		padding: 12px;
		overflow-y: auto;
		font-size: 12px;
		color: #ccc;
		flex-shrink: 0;
	}
	.properties-panel h3 {
		margin: 0 0 12px;
		font-size: 14px;
		color: #fff;
		border-bottom: 1px solid #333;
		padding-bottom: 8px;
	}
	.section {
		margin-bottom: 16px;
	}
	.section h4 {
		margin: 0 0 8px;
		font-size: 13px;
		color: #aaa;
	}
	.section h5 {
		margin: 8px 0 4px;
		font-size: 12px;
		color: #888;
	}
	.field-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 6px;
		gap: 8px;
	}
	.field-row input, .field-row select {
		width: 120px;
		background: #333;
		border: 1px solid #555;
		color: #fff;
		padding: 3px 6px;
		border-radius: 3px;
		font-size: 12px;
	}
	.btn {
		width: 100%;
		padding: 6px;
		border-radius: 4px;
		border: none;
		cursor: pointer;
		font-size: 12px;
		margin-top: 8px;
	}
	.btn.danger { background: #5c1a1a; color: #ff6b6b; }
	.btn.sm { width: auto; padding: 3px 8px; margin-top: 0; font-size: 11px; background: #2a4a6a; color: #8ac; }
	.no-selection { color: #555; font-style: italic; text-align: center; padding: 20px 0; }
	.grid-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
	.panel-row { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
	.panel-label { min-width: 20px; color: #8ac; font-family: monospace; font-size: 11px; }
	.panel-row select { flex: 1; background: #333; border: 1px solid #555; color: #fff; padding: 2px 4px; border-radius: 3px; font-size: 11px; }
	.effect-entry { display: flex; justify-content: space-between; padding: 4px 6px; margin: 2px 0; border-radius: 4px; background: #222; cursor: pointer; }
	.effect-entry.active { background: #2a2a4a; border: 1px solid #4a4a8a; }
	.effect-label { font-size: 12px; color: #8ac; }
	.effect-time { font-size: 10px; color: #666; font-family: monospace; }
	.effect-params { padding: 4px 6px; background: #1a1a2a; border-radius: 4px; margin-bottom: 6px; }
	.param-label { font-size: 11px; color: #888; display: block; margin-bottom: 4px; }
	.easing-section { margin: 6px 0; }
</style>
