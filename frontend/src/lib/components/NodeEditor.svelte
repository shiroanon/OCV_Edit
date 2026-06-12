<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { SvelteFlow, Background, BackgroundVariant, Controls, MiniMap } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import '@xyflow/svelte/dist/base.css';
	import VideoClipNode from '$lib/nodes/VideoClipNode.svelte';
	import TransitionNode from '$lib/nodes/TransitionNode.svelte';
	import EffectNode from '$lib/nodes/EffectNode.svelte';
	import SceneInitNode from '$lib/nodes/SceneInitNode.svelte';
	import GridSceneNode from '$lib/nodes/GridSceneNode.svelte';
	import type { Node, Edge, NodeTypes, Connection } from '@xyflow/svelte';
	import type { EditPlan } from '$lib/types/plan';
	import { currentPlan, selectedSceneIndex, selectedClipIndex, planSettingsSelected } from '$lib/stores/plan';
	import { removeClip, removeEffect, removeScene, setTransition, addGridScene } from '$lib/stores/plan';

	const nodeTypes: NodeTypes = {
		videoClip: VideoClipNode,
		transition: TransitionNode,
		effect: EffectNode,
		sceneInit: SceneInitNode,
		gridScene: GridSceneNode
	};

	const AVAILABLE_NODES = [
		{
			type: 'videoClip',
			label: 'Video Clip',
			description: 'A video source with trim and speed controls',
		},
		{
			type: 'transition',
			label: 'Transition',
			description: 'Effect between two clips (slide, zoom, wipe, etc.)',
		},
		{
			type: 'gridScene',
			label: 'Grid Scene',
			description: 'Multi-panel grid layout (e.g. 2×2, 3×3)',
		},
	];

	const TRANSITION_TYPES = [
		{ type: 'transition', transitionType: 'slide', label: 'Slide', description: 'Slide one clip out revealing the next (left/right/up/down)', defaultParams: { direction: 'left', easing: 'ease_in_out' } },
		{ type: 'transition', transitionType: 'zoom', label: 'Zoom', description: 'Zoom and crossfade between clips', defaultParams: { mode: 'in', easing: 'ease_in_out' } },
		{ type: 'transition', transitionType: 'grid_wipe', label: 'Grid Wipe', description: 'Blocks flip staggered in grid pattern', defaultParams: { cols: 6, rows: 4, stagger: 'row', easing: 'ease_in_out' } },
		{ type: 'transition', transitionType: 'flash', label: 'Flash', description: 'Frame → solid color → frame', defaultParams: { color: [255, 255, 255], flash_point: 0.35, easing: 'ease_in_out' } },
		{ type: 'transition', transitionType: 'radial_wipe', label: 'Radial Wipe', description: 'Growing circle reveals next clip', defaultParams: { origin: [0.5, 0.5], easing: 'ease_in_out' } },
		{ type: 'transition', transitionType: 'zoom_in', label: 'Zoom In', description: 'Aggressive zoom with blur peak', defaultParams: { max_zoom: 5.0, blur_peak: 3.0, easing: [0.45, 0, 0.55, 1] } },
	];

	const EFFECT_TYPES = [
		{ type: 'effect', effectType: 'ZoomEffect', label: 'Zoom Effect', description: 'Zoom in/out animation', defaultParams: { start_zoom: 1.1, end_zoom: 1.0, easing: 'ease_in_out' } },
		{ type: 'effect', effectType: 'BlurEffect', label: 'Blur Effect', description: 'Gaussian blur', defaultParams: { start_blur: 0, end_blur: 5, easing: 'ease_in_out' } },
		{ type: 'effect', effectType: 'RGBShiftEffect', label: 'RGB Shift', description: 'Chromatic aberration', defaultParams: { start_shift: 0, end_shift: 0.083, angle: 0, easing: 'ease_in_out' } },
		{ type: 'effect', effectType: 'ColorAdjustEffect', label: 'Color Adjust', description: 'Saturation/contrast/brightness', defaultParams: { start_params: { saturation: 1.0, contrast: 1.0, brightness: 0.0 }, end_params: { saturation: 1.2, contrast: 1.1, brightness: 5.0 }, easing: 'ease_in_out' } },
		{ type: 'effect', effectType: 'ZoomToPoint', label: 'Zoom To Point', description: 'TikTok-style focus pull', defaultParams: { center: [0.5, 0.5], start_zoom: 1.0, end_zoom: 1.6, easing: 'ease_in_out' } },
		{ type: 'effect', effectType: 'KenBurnsEffect', label: 'Ken Burns', description: 'Slow pan & zoom', defaultParams: { center: [0.5, 0.5], zoom_out: 1.06, zoom_in: 1.18, drift_x: 0.02, drift_y: 0.01, easing: 'ease_in_out' } },
		{ type: 'effect', effectType: 'PanelSlideEffect', label: 'Panel Slide', description: 'Slide panel in/out', defaultParams: { direction: 'left', start_offset: 1.0, end_offset: 0.0, easing: 'ease_out' } },
		{ type: 'effect', effectType: 'PanelPulseEffect', label: 'Panel Pulse', description: 'Brief scale pulse', defaultParams: { start_scale: 1.0, pulse_scale: 1.15, end_scale: 1.0, easing: 'ease_out' } },
		{ type: 'effect', effectType: 'PanelBounceEffect', label: 'Panel Bounce', description: 'Quick displacement bounce', defaultParams: { direction: 'up', amplitude: 0.08, easing: 'ease_out' } },
		{ type: 'effect', effectType: 'PanelSpinEffect', label: 'Panel Spin', description: 'Rotation wobble', defaultParams: { max_angle: 3.0, easing: 'ease_out' } },
		{ type: 'effect', effectType: 'GridScanEffect', label: 'Grid Scan', description: 'Scanning bars overlay', defaultParams: { num_bars: 240.0, bar_speed: 0.8, bar_width: 0.05, easing: 'linear' } },
		{ type: 'effect', effectType: 'GridFlashEffect', label: 'Grid Flash', description: 'Brightness flash', defaultParams: { intensity: 0.5, easing: 'linear' } },
		{ type: 'effect', effectType: 'GridGlitchEffect', label: 'Grid Glitch', description: 'Random slice displacement', defaultParams: { intensity: 1.0, easing: 'linear' } },
		{ type: 'effect', effectType: 'GridWaveWarpEffect', label: 'Grid Wave', description: 'Horizontal wave warp', defaultParams: { frequency: 20.0, amplitude: 0.03, speed: 5.0, easing: 'linear' } },
		{ type: 'effect', effectType: 'GridPixelateEffect', label: 'Grid Pixelate', description: 'Progressive pixelation', defaultParams: { max_pixels: 400.0, min_pixels: 25.0, easing: 'linear' } },
		{ type: 'effect', effectType: 'GridChromaticEffect', label: 'Grid Chromatic', description: 'Chromatic aberration', defaultParams: { intensity: 1.0, angle: 0.0, easing: 'linear' } },
		{ type: 'effect', effectType: 'YoloEmissionEffect', label: 'YOLO Emission', description: 'Pulsing aura around people', defaultParams: { inner_color: [180, 220, 255], outer_color: [30, 80, 255], inner_radius: 0.014, outer_radius: 0.047, intensity: 1.0, pulse_speed: 2.5, pulse_amplitude: 0.15, easing: 'linear' } },
		{ type: 'effect', effectType: 'YoloTextEffect', label: 'YOLO Text', description: 'Depth-composited text overlay', defaultParams: { text: 'Hello', font_size: 0.074, position: 'bottom_center', color: [255, 255, 255], opacity: 1.0, easing: 'linear' } },
	];

	let nodes = $state<Node[]>([]);
	let edges = $state<Edge[]>([]);
	let selectedNodeId = $state<string | null>(null);

	let contextMenu = $state<{ x: number; y: number } | null>(null);
	let contextSearch = $state('');

	let allMenuItems = $derived([...AVAILABLE_NODES, ...TRANSITION_TYPES, ...EFFECT_TYPES]);

	let filteredNodes = $derived(
		allMenuItems.filter(
			(n) =>
				n.label.toLowerCase().includes(contextSearch.toLowerCase()) ||
				n.type.toLowerCase().includes(contextSearch.toLowerCase()) ||
				(n.effectType && n.effectType.toLowerCase().includes(contextSearch.toLowerCase())) ||
				(n.transitionType && n.transitionType.toLowerCase().includes(contextSearch.toLowerCase()))
		)
	);

	function isValidConnection(connection: Connection): boolean {
		const sourceType = nodes.find((n) => n.id === connection.source)?.type;
		const targetType = nodes.find((n) => n.id === connection.target)?.type;
		if (!sourceType || !targetType) return false;
		if (sourceType === 'videoClip' && targetType === 'effect') {
			return connection.sourceHandle === 'effect-out';
		}
		if (sourceType === 'videoClip' && targetType === 'transition') return true;
		if (sourceType === 'transition' && targetType === 'videoClip') return true;
		return false;
	}

	function createClipNode(si: number, ci: number, x: number, y: number, overrides: Partial<Record<string, unknown>> = {}): Node {
		return {
			id: `clip-${si}-${ci}`,
			type: 'videoClip',
			position: { x, y },
			data: {
				label: `Clip ${si}.${ci}`,
				filepath: 'videos/1.mp4',
				startTime: 0,
				duration: 3,
				speed: 1,
				effects: [],
				sceneIndex: si,
				clipIndex: ci,
				...overrides
			}
		};
	}

	function createEffectNode(si: number, ci: number, ei: number, x: number, y: number, type = 'ZoomEffect'): Node {
		const entry = EFFECT_TYPES.find((e) => e.effectType === type);
		const params = entry?.defaultParams ? { ...entry.defaultParams } : { easing: 'ease_in_out' };

		return {
			id: `effect-${si}-${ci}-${ei}`,
			type: 'effect',
			position: { x, y },
			data: {
				label: type,
				effectType: type,
				params,
				startTime: 0,
				duration: 0.3,
				sceneIndex: si,
				clipIndex: ci,
				effectIndex: ei
			}
		};
	}

	function createTransitionNode(si: number, x: number, y: number, subType = 'slide'): Node {
		const entry = TRANSITION_TYPES.find((t) => t.transitionType === subType);
		const params = entry?.defaultParams ? { ...entry.defaultParams } : { direction: 'left', easing: 'ease_in_out' };

		return {
			id: `trans-${si}`,
			type: 'transition',
			position: { x, y },
			data: {
				label: subType,
				transitionType: subType,
				duration: 0.2,
				params,
				...params,
				sceneIndex: si
			}
		};
	}

	function planToGraph(plan: EditPlan) {
		const newNodes: Node[] = [];
		const newEdges: Edge[] = [];

		// Scene init node at top-left
		newNodes.push({
			id: 'scene-init',
			type: 'sceneInit',
			position: { x: 40, y: 40 },
			draggable: false,
			data: {
				label: 'Scene Init',
				fps: plan.fps,
				outputSize: plan.output_size,
				resizeMode: plan.resize_mode
			}
		});

		let xOffset = 40;
		const CLIP_Y = 180;
		const EFF_Y = 260;

		plan.scenes.forEach((scene, si) => {
			if (scene.is_grid) {
				const panelCount = scene.clips[0]?.panels?.length || 4;
				const cols = Math.min(panelCount, 3);
				const rows = Math.ceil(panelCount / cols);
				newNodes.push({
					id: `grid-${si}`,
					type: 'gridScene',
					position: { x: xOffset, y: CLIP_Y },
					data: {
						label: `Grid ${si}`,
						layout: [rows, cols],
						gap: 2,
						panelCount,
						duration: scene.out_dur,
						sceneIndex: si
					}
				});
				xOffset += 220;

				if (scene.transition) {
					const transNode = createTransitionNode(si, xOffset, CLIP_Y + 40, scene.transition.type);
					newNodes.push(transNode);
					xOffset += 180;
					if (si < plan.scenes.length - 1) {
						const nextScene = plan.scenes[si + 1];
						const nextId = nextScene?.is_grid ? `grid-${si + 1}` : `clip-${si + 1}-0`;
						newEdges.push({
							id: `e-${transNode.id}-${nextId}`,
							source: transNode.id, sourceHandle: 'out',
							target: nextId, targetHandle: 'in'
						});
					}
				}

				xOffset += 60;
				return;
			}

			scene.clips.forEach((clip, ci) => {
				const clipNode = createClipNode(si, ci, xOffset, CLIP_Y, {
					filepath: clip.filepath,
					startTime: clip.start_time,
					duration: clip.duration,
					speed: clip.speed,
					effects: clip.effects
				});
				xOffset += 220;
				newNodes.push(clipNode);

				clip.effects.forEach((eff, ei) => {
					const effNode = createEffectNode(si, ci, ei, xOffset, EFF_Y + ei * 80, eff.type);
					effNode.data = { ...effNode.data, params: eff.params, startTime: eff.start_time, duration: eff.duration };
					newNodes.push(effNode);
					newEdges.push({
						id: `e-${clipNode.id}-${effNode.id}`,
						source: clipNode.id,
						sourceHandle: 'effect-out',
						target: effNode.id,
						targetHandle: 'in'
					});
				});
				xOffset += 280;
			});

			if (scene.transition) {
				const transNode = createTransitionNode(si, xOffset, CLIP_Y + 40);
				newNodes.push(transNode);
				const lastClipId = scene.is_grid ? `grid-${si}` : `clip-${si}-${scene.clips.length - 1}`;
				newEdges.push({
					id: `e-${lastClipId}-${transNode.id}`,
					source: lastClipId,
					sourceHandle: 'out',
					target: transNode.id,
					targetHandle: 'in'
				});
				xOffset += 180;

				if (si < plan.scenes.length - 1) {
					const nextScene = plan.scenes[si + 1];
					const nextClipId = nextScene?.is_grid ? `grid-${si + 1}` : `clip-${si + 1}-0`;
					newEdges.push({
						id: `e-${transNode.id}-${nextClipId}`,
						source: transNode.id,
						sourceHandle: 'out',
						target: nextClipId,
						targetHandle: 'in'
					});
				}
			}

			xOffset += 60;
		});

		nodes = newNodes;
		edges = newEdges;
	}

	function findNearestClip(x: number, y: number): [[number, number] | null, string | null] {
		let bestDist = Infinity;
		let bestId: string | null = null;
		let bestIdx: [number, number] | null = null;

		for (const n of nodes) {
			if (n.type !== 'videoClip') continue;
			const dx = n.position.x - x;
			const dy = n.position.y - y;
			const dist = Math.sqrt(dx * dx + dy * dy);
			if (dist < bestDist) {
				bestDist = dist;
				bestId = n.id;
				const d = n.data as Record<string, unknown>;
				bestIdx = [d.sceneIndex as number, d.clipIndex as number];
			}
		}
		return [bestIdx, bestId];
	}

	function addNodeFromMenu(nodeType: string, subType?: string) {
		if (!contextMenu) return;
		const { x, y } = contextMenu;

		if (nodeType === 'videoClip') {
			const si = nodes.filter((n) => n.type === 'videoClip').length;
			nodes = [...nodes, createClipNode(si, 0, x - 100, y - 50)];
		} else if (nodeType === 'gridScene') {
			const plan = get(currentPlan);
			const fp = 'videos/1.mp4';
			const updated = addGridScene(plan, 2, 2, fp);
			currentPlan.set(updated);
			const si = plan.scenes.length;
			nodes = [...nodes, {
				id: `grid-${si}`,
				type: 'gridScene',
				position: { x: x - 100, y: y - 50 },
				data: {
					label: `Grid ${si}`,
					layout: [2, 2],
					gap: 2,
					panelCount: 4,
					duration: 4,
					sceneIndex: si
				}
			}];
		} else if (nodeType === 'transition') {
			const si = nodes.filter((n) => n.type === 'transition').length;
			const transNode = createTransitionNode(si + 1, x - 100, y - 50, subType);
			nodes = [...nodes, transNode];

			const clips = nodes.filter((n) => n.type === 'videoClip');
			if (clips.length > 0) {
				const lastClip = clips[clips.length - 1];
				nodes = [...nodes.filter((n) => n.id !== transNode.id), transNode];
			}
		} else if (nodeType === 'effect') {
			const [idx, clipId] = findNearestClip(x, y);
			const si = idx ? idx[0] : Math.max(0, nodes.filter((n) => n.type === 'videoClip').length - 1);
			const ci = idx ? idx[1] : 0;

			const existingEffects = nodes.filter((n) => n.type === 'effect' && (n.data as Record<string, unknown>).sceneIndex === si && (n.data as Record<string, unknown>).clipIndex === ci);
			const ei = existingEffects.length;

			const effNode = createEffectNode(si, ci, ei, x - 100, y - 50, subType || 'ZoomEffect');
			nodes = [...nodes, effNode];

			if (clipId) {
				edges = [...edges, {
					id: `e-${clipId}-${effNode.id}`,
					source: clipId,
					sourceHandle: 'effect-out',
					target: effNode.id,
					targetHandle: 'in'
				}];
			}
		}

		contextMenu = null;
		contextSearch = '';
	}

	function seedDemoPlan() {
		currentPlan.set({
			output_size: [1920, 1080],
			fps: 30,
			resize_mode: 'fill',
			global_effects: [],
			scenes: [
				{
					out_dur: 4,
					video_file: 'videos/1.mp4',
					is_grid: false,
					clips: [
						{
							filepath: 'videos/1.mp4',
							start_time: 0,
							duration: 4,
							speed: 1,
							effects: [
								{
									type: 'ZoomEffect',
									start_time: 0,
									duration: 0.3,
									params: { start_zoom: 1.1, end_zoom: 1.0, easing: 'ease_out' }
								}
							]
						}
					],
					transition: { type: 'slide', duration: 0.2, params: { direction: 'left', easing: 'ease_in_out' } }
				},
				{
					out_dur: 3,
					video_file: 'videos/4.mp4',
					is_grid: false,
					clips: [
						{
							filepath: 'videos/4.mp4',
							start_time: 0,
							duration: 3,
							speed: 1,
							effects: []
						}
					],
					transition: null
				}
			]
		});
	}

	onMount(() => {
		const unsub = currentPlan.subscribe((plan) => {
			if (plan.scenes.length > 0) {
				planToGraph(plan);
			}
		});
		// seed a demo plan if empty on first load
		if (get(currentPlan).scenes.length === 0) {
			seedDemoPlan();
		}
		return unsub;
	});

	function onPaneContextMenu(event: { event: MouseEvent }) {
		event.event.preventDefault();
		contextMenu = { x: event.event.offsetX, y: event.event.offsetY };
		contextSearch = '';
	}

	function onNodeContextMenu(event: { node: Node; event: MouseEvent }) {
		event.event.preventDefault();
		selectedNodeId = event.node.id;
		planSettingsSelected.set(false);
		const rect = (event.event.currentTarget as HTMLElement)?.getBoundingClientRect?.();
		const flowEl = document.querySelector('.svelte-flow');
		const bounds = flowEl?.getBoundingClientRect();
		if (bounds) {
			contextMenu = { x: event.event.clientX - bounds.left, y: event.event.clientY - bounds.top };
		} else {
			contextMenu = { x: event.event.offsetX, y: event.event.offsetY };
		}
		contextSearch = '';
	}

	function closeMenu() {
		contextMenu = null;
		contextSearch = '';
	}

	function handleNodeClick(event: { node: Node; event: MouseEvent }) {
		selectedNodeId = event.node.id;
		if (event.node.type === 'sceneInit') {
			planSettingsSelected.set(true);
			selectedSceneIndex.set(null);
			selectedClipIndex.set(null);
			return;
		}
		planSettingsSelected.set(false);
		const d = event.node.data as Record<string, unknown>;
		if (d.sceneIndex !== undefined) {
			selectedSceneIndex.set(d.sceneIndex as number);
		}
		if (d.clipIndex !== undefined) {
			selectedClipIndex.set(d.clipIndex as number);
		}
	}

	function onPaneClick(_event: { event: MouseEvent }) {
		selectedNodeId = null;
		selectedSceneIndex.set(null);
		selectedClipIndex.set(null);
		planSettingsSelected.set(false);
	}

	function onKeyDown(event: KeyboardEvent) {
		if (event.key === 'Escape') closeMenu();
		if ((event.key === 'Delete' || event.key === 'Backspace') && selectedNodeId) {
			deleteSelectedNode();
		}
	}

	function deleteSelectedNode() {
		if (!selectedNodeId) return;
		const node = nodes.find((n) => n.id === selectedNodeId);
		if (!node || node.id === 'scene-init') return;

		const d = node.data as Record<string, unknown>;
		const si = d.sceneIndex as number | undefined;
		const ci = d.clipIndex as number | undefined;
		const ei = d.effectIndex as number | undefined;

		const plan = get(currentPlan);

		if (node.type === 'videoClip' && si !== undefined && ci !== undefined) {
			const updated = removeClip(plan, si, ci);
			currentPlan.set(updated);
		} else if (node.type === 'effect' && si !== undefined && ci !== undefined && ei !== undefined) {
			const updated = removeEffect(plan, si, ci, ei);
			currentPlan.set(updated);
		} else if (node.type === 'transition' && si !== undefined) {
			const updated = setTransition(plan, si, null);
			currentPlan.set(updated);
		}

		nodes = nodes.filter((n) => n.id !== selectedNodeId);
		edges = edges.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId);
		selectedNodeId = null;
		selectedSceneIndex.set(null);
		selectedClipIndex.set(null);
	}

	function handleDrop(event: DragEvent) {
		event.preventDefault();
		const data = event.dataTransfer?.getData('application/json');
		if (!data) return;
		try {
			const parsed = JSON.parse(data);
			const bounds = document.querySelector('.svelte-flow')?.getBoundingClientRect();
			const x = bounds ? event.clientX - bounds.left - 100 : 200;
			const y = bounds ? event.clientY - bounds.top - 50 : 200;

			if (parsed.type === 'video') {
				const si = nodes.filter((n) => n.type === 'videoClip').length;
				nodes = [...nodes, createClipNode(si, 0, x, y, { filepath: parsed.path })];
			}
		} catch { /* ignore */ }
	}

	function allowDrop(event: DragEvent) {
		event.preventDefault();
	}
</script>

<svelte:window onkeydown={onKeyDown} />

<div
	class="editor-container"
	role="application"
	ondrop={handleDrop}
	ondragover={allowDrop}
>
	{#if nodes.length === 0}
		<div class="empty-state">
			<p>No clips yet</p>
			<small>Right-click the canvas to add nodes, or click <strong>+ Scene</strong> in the toolbar</small>
		</div>
	{/if}

	<SvelteFlow
		{nodeTypes}
		bind:nodes
		bind:edges
		fitView
		colorMode="dark"
		{isValidConnection}
		nodesDraggable={true}
		nodesConnectable={true}
		elementsSelectable={true}
		onnodeclick={handleNodeClick}
		onnodecontextmenu={onNodeContextMenu}
		onpanecontextmenu={onPaneContextMenu}
		onpaneclick={onPaneClick}
	>
		<Controls />
		<Background variant={BackgroundVariant.Dots} gap={20} />
		<MiniMap
			nodeColor={(n: Node) => {
				if (n.type === 'videoClip') return '#4a4a8a';
				if (n.type === 'transition') return '#4a8a4a';
				if (n.type === 'effect') return '#8a4a8a';
				if (n.type === 'sceneInit') return '#6a4aff';
				return '#555';
			}}
		/>
	</SvelteFlow>

	{#if contextMenu}
		<div
			class="context-menu"
			style="left: {contextMenu.x}px; top: {contextMenu.y}px"
			role="menu"
			onclick={(e) => e.stopPropagation()}
		>
			{#if selectedNodeId}
				<button
					class="context-item delete-item"
					onclick={() => { deleteSelectedNode(); contextMenu = null; }}
					role="menuitem"
				>
					<span class="item-label">🗑 Delete</span>
					<span class="item-desc">Remove this node</span>
				</button>
				<div class="context-divider"></div>
			{/if}
			<div class="context-header">
				<input
					type="text"
					placeholder="Search nodes..."
					bind:value={contextSearch}
					autofocus
					onclick={(e) => e.stopPropagation()}
				/>
			</div>
			<div class="context-list">
				{#each filteredNodes as item}
					<button
						class="context-item"
						onclick={() => {
							const rec = item as Record<string, unknown>;
							addNodeFromMenu(item.type, (rec.effectType || rec.transitionType) as string | undefined);
						}}
						role="menuitem"
					>
						<span class="item-label">{item.label}</span>
						<span class="item-desc">{item.description}</span>
					</button>
				{/each}
				{#if filteredNodes.length === 0}
					<div class="no-results">No matching nodes</div>
				{/if}
			</div>
		</div>
		<div class="context-backdrop" onclick={closeMenu} oncontextmenu={(e) => e.preventDefault()} />
	{/if}
</div>

<style>
	.editor-container {
		width: 100%;
		height: 100%;
		position: relative;
	}
	.empty-state {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		text-align: center;
		color: #555;
		z-index: 10;
		pointer-events: none;
	}
	.empty-state p { font-size: 18px; margin: 0 0 8px; }
	.empty-state small { font-size: 13px; color: #444; }

	.context-backdrop {
		position: fixed;
		inset: 0;
		z-index: 99;
	}
	.context-menu {
		position: absolute;
		z-index: 100;
		background: #1a1a2e;
		border: 1px solid #4a4a8a;
		border-radius: 8px;
		min-width: 240px;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
		overflow: hidden;
	}
	.context-header {
		padding: 8px;
		border-bottom: 1px solid #333;
	}
	.context-header input {
		width: 100%;
		background: #0d0d1a;
		border: 1px solid #4a4a8a;
		color: #e0e0e0;
		padding: 6px 10px;
		border-radius: 4px;
		font-size: 13px;
		outline: none;
		box-sizing: border-box;
	}
	.context-header input:focus {
		border-color: #6a4aff;
	}
	.context-list {
		max-height: 240px;
		overflow-y: auto;
	}
	.context-item {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		color: #ccc;
		padding: 8px 12px;
		cursor: pointer;
		font-size: 13px;
	}
	.context-item:hover {
		background: #2a2a4a;
		color: #fff;
	}
	.delete-item { color: #ff6b6b; }
	.delete-item:hover { background: #3e1212; color: #ff4444; }
	.context-divider {
		height: 1px;
		background: #333;
		margin: 4px 0;
	}
	.item-label {
		font-weight: 600;
		display: block;
	}
	.item-desc {
		font-size: 11px;
		color: #666;
		display: block;
		margin-top: 2px;
	}
	.no-results {
		padding: 12px;
		color: #555;
		font-style: italic;
		text-align: center;
		font-size: 12px;
	}
</style>
