<script lang="ts">
	import { currentPlan } from '$lib/stores/plan';
	import { api } from '$lib/api/client';
	import type { EditPlan, FileEntry } from '$lib/types/plan';

	let planName = $state('my_edit');
	let videos = $state<FileEntry[]>([]);
	let isSaving = $state(false);
	let isRendering = $state(false);
	let renderProgress = $state<string | null>(null);
	let statusMsg = $state<string | null>(null);
	let showAutoEdit = $state(false);
	let autoEditAudioFile = $state('audios/Only Fire - Up n Down (Audio) [se9ZcIEN_gk].m4a');
	let autoEditDuration = $state(30);
	let autoEditBusy = $state(false);

	async function loadVideos() {
		try {
			videos = await api.videos();
		} catch {
			videos = [];
		}
	}

	async function handleSave() {
		isSaving = true;
		try {
			let plan: EditPlan;
			const unsub = currentPlan.subscribe((p) => (plan = p))();
			await api.savePlan(planName, plan);
			unsub();
			statusMsg = `Saved as "${planName}"`;
		} catch (e) {
			statusMsg = `Save failed: ${e}`;
		} finally {
			isSaving = false;
			setTimeout(() => (statusMsg = null), 3000);
		}
	}

	async function handleLoad() {
		try {
			const loaded = await api.loadPlan(planName);
			statusMsg = `Loaded "${planName}"`;
			currentPlan.set(loaded);
		} catch (e) {
			statusMsg = `Load failed: ${e}`;
		}
		setTimeout(() => (statusMsg = null), 3000);
	}

	async function handleRender() {
		isRendering = true;
		renderProgress = 'Rendering...';
		try {
			let plan: EditPlan;
			const unsub = currentPlan.subscribe((p) => (plan = p))();
			const blob = await api.render(plan, 'frontend_render.mp4');
			unsub();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = 'render.mp4';
			a.click();
			URL.revokeObjectURL(url);
			renderProgress = 'Render complete!';
		} catch (e) {
			renderProgress = `Render failed: ${e}`;
		} finally {
			isRendering = false;
			setTimeout(() => (renderProgress = null), 5000);
		}
	}

	function handleExportJson() {
		let plan: EditPlan;
		const unsub = currentPlan.subscribe((p) => (plan = p))();
		unsub();
		const blob = new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${planName}.json`;
		a.click();
		URL.revokeObjectURL(url);
	}

	function handleImportJson() {
		const input = document.createElement('input');
		input.type = 'file';
		input.accept = '.json';
		input.onchange = async () => {
			const file = input.files?.[0];
			if (!file) return;
			try {
				const text = await file.text();
				const plan = JSON.parse(text) as EditPlan;
				currentPlan.set(plan);
				planName = file.name.replace('.json', '');
				statusMsg = `Imported "${file.name}"`;
			} catch (e) {
				statusMsg = `Import failed: ${e}`;
			}
			setTimeout(() => (statusMsg = null), 3000);
		};
		input.click();
	}

	async function handleAutoEdit() {
		autoEditBusy = true;
		try {
			const plan = await api.autoEdit({
				audio_path: autoEditAudioFile,
				duration: autoEditDuration || null,
				resize_mode: 'fill',
				transition_chance: 0.5,
				grid_chance: 0.0,
			});
			if (plan) {
				currentPlan.set(plan);
				statusMsg = 'AutoEdit plan loaded';
			}
		} catch (e) {
			statusMsg = `AutoEdit failed: ${e}`;
		} finally {
			autoEditBusy = false;
			showAutoEdit = false;
			setTimeout(() => (statusMsg = null), 5000);
		}
	}

	function addNewScene() {
		let plan: EditPlan;
		const unsub = currentPlan.subscribe((p) => (plan = p))();
		unsub();
		const newPlan = {
			...plan,
			scenes: [
				...plan.scenes,
				{
					out_dur: 3,
					video_file: 'videos/test1.mp4',
					is_grid: false,
					clips: [
						{
							filepath: 'videos/test1.mp4',
							start_time: 0,
							duration: 3,
							speed: 1,
							effects: []
						}
					],
					transition: null
				}
			]
		};
		currentPlan.set(newPlan);
	}

	function onDragStart(event: DragEvent, video: FileEntry) {
		event.dataTransfer?.setData('application/json', JSON.stringify({ type: 'video', ...video }));
		event.dataTransfer!.effectAllowed = 'copy';
	}

	$effect(() => {
		loadVideos();
	});
</script>

<header class="toolbar">
	<div class="toolbar-left">
		<h1>OCV Edit</h1>
		<input
			class="plan-name"
			bind:value={planName}
			placeholder="Plan name"
		/>
		<button class="btn" onclick={handleSave} disabled={isSaving}>
			💾 Save
		</button>
		<button class="btn" onclick={handleLoad}>📂 Load</button>
		<button class="btn" onclick={handleExportJson}>📥 Export</button>
		<button class="btn" onclick={handleImportJson}>📤 Import</button>
		<button class="btn primary" onclick={addNewScene}>+ Scene</button>
	</div>

	<div class="toolbar-right">
		<div class="media-dropdown">
			<span class="dropdown-label">Videos</span>
			<div class="media-list">
				{#each videos as v}
					<div
						class="media-item"
						draggable="true"
						ondragstart={(e) => onDragStart(e, v)}
					>
						{v.name}
					</div>
				{/each}
				{#if videos.length === 0}
					<span class="no-media">No videos found</span>
				{/if}
			</div>
		</div>

		<button class="btn accent" onclick={handleRender} disabled={isRendering}>
			🎬 Render
		</button>
		<button class="btn" onclick={() => showAutoEdit = !showAutoEdit}>
			🤖 AutoEdit
		</button>
	</div>
</header>

{#if showAutoEdit}
	<div class="dialog-overlay" onclick={() => showAutoEdit = false} onkeydown={(e) => { if (e.key === 'Escape') showAutoEdit = false; }} role="dialog" tabindex="0">
		<div class="dialog" onclick={(e) => e.stopPropagation()}>
			<h3>AutoEdit Settings</h3>
			<label class="field-row">
				<span>Audio File</span>
				<input
					type="text"
					bind:value={autoEditAudioFile}
				/>
			</label>
			<label class="field-row">
				<span>Duration (sec)</span>
				<input
					type="number"
					bind:value={autoEditDuration}
					min="5"
					step="5"
				/>
			</label>
			<div class="dialog-actions">
				<button class="btn" onclick={() => showAutoEdit = false}>Cancel</button>
				<button class="btn primary" onclick={handleAutoEdit} disabled={autoEditBusy}>
					{autoEditBusy ? 'Generating...' : 'Generate Plan'}
				</button>
			</div>
		</div>
	</div>
{/if}

{#if statusMsg}
	<div class="status-bar">{statusMsg}</div>
{/if}
{#if renderProgress}
	<div class="status-bar render">{renderProgress}</div>
{/if}

<style>
	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		background: #1a1a2e;
		border-bottom: 1px solid #333;
		padding: 8px 16px;
		gap: 16px;
		z-index: 10;
	}
	.toolbar-left, .toolbar-right {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.toolbar h1 {
		font-size: 16px;
		margin: 0;
		color: #fff;
		font-weight: 700;
	}
	.plan-name {
		background: #2a2a4a;
		border: 1px solid #4a4a8a;
		color: #fff;
		padding: 4px 8px;
		border-radius: 4px;
		font-size: 13px;
		width: 140px;
	}
	.btn {
		background: #333;
		color: #ddd;
		border: 1px solid #555;
		padding: 5px 12px;
		border-radius: 4px;
		cursor: pointer;
		font-size: 12px;
		white-space: nowrap;
	}
	.btn.primary { background: #2d1b69; border-color: #6a4aff; color: #b388ff; }
	.btn.accent { background: #1b5e20; border-color: #4caf50; color: #a5d6a7; }
	.btn:disabled { opacity: 0.5; cursor: default; }
	.media-dropdown {
		position: relative;
		display: inline-block;
	}
	.dropdown-label {
		background: #333;
		color: #aaa;
		padding: 5px 12px;
		border-radius: 4px;
		font-size: 12px;
		cursor: pointer;
		border: 1px solid #555;
	}
	.media-list {
		display: none;
		position: absolute;
		top: 100%;
		right: 0;
		background: #1a1a2e;
		border: 1px solid #333;
		border-radius: 4px;
		max-height: 300px;
		overflow-y: auto;
		min-width: 200px;
		z-index: 100;
	}
	.media-dropdown:hover .media-list { display: block; }
	.media-item {
		padding: 6px 12px;
		cursor: grab;
		font-size: 12px;
		color: #ccc;
	}
	.media-item:hover { background: #2a2a4a; }
	.no-media { padding: 8px; color: #555; font-style: italic; font-size: 11px; }
	.status-bar {
		background: #1b5e20;
		color: #a5d6a7;
		padding: 4px 16px;
		font-size: 12px;
	}
	.status-bar.render { background: #5c1a1a; color: #ff6b6b; }
	.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 200; }
	.dialog { background: #1a1a2e; border: 1px solid #4a4a8a; border-radius: 8px; padding: 20px; min-width: 340px; }
	.dialog h3 { margin: 0 0 16px; font-size: 15px; color: #fff; }
	.field-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 8px; }
	.field-row input { width: 200px; background: #333; border: 1px solid #555; color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
	.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
