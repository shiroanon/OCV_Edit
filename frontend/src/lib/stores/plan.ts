import { writable, derived } from 'svelte/store';
import type { EditPlan, SceneData, ClipData, EffectEntry, TransitionData, PanelData } from '$lib/types/plan';

function createDefaultPlan(): EditPlan {
	return {
		output_size: [1920, 1080],
		fps: 30,
		resize_mode: 'fill',
		global_effects: [],
		scenes: []
	};
}

export const currentPlan = writable<EditPlan>(createDefaultPlan());
export const selectedSceneIndex = writable<number | null>(null);
export const selectedClipIndex = writable<number | null>(null);
export const planSettingsSelected = writable(false);
export const previewTime = writable(0);
export const isPlaying = writable(false);

export const totalDuration = derived(currentPlan, ($plan) => {
	return $plan.scenes.reduce((sum, s) => {
		const transDur = s.transition?.duration ?? 0;
		return sum + s.out_dur + transDur;
	}, 0);
});

export function addScene(plan: EditPlan, scene: SceneData): EditPlan {
	return { ...plan, scenes: [...plan.scenes, scene] };
}

export function addGridScene(plan: EditPlan, rows: number, cols: number, filepath: string): EditPlan {
	const panelCount = rows * cols;
	const panels: PanelData[] = Array.from({ length: panelCount }, (_, i) => ({
		file: filepath,
		start_time: 0,
		speed: 1,
		effects: []
	}));
	const scene: SceneData = {
		out_dur: 4,
		video_file: filepath,
		is_grid: true,
		clips: [{
			filepath,
			start_time: 0,
			duration: 4,
			speed: 1,
			effects: [],
			is_grid: true,
			panels
		}],
		transition: null
	};
	return addScene(plan, scene);
}

export function removeScene(plan: EditPlan, index: number): EditPlan {
	const scenes = plan.scenes.filter((_, i) => i !== index);
	return { ...plan, scenes };
}

export function updateScene(plan: EditPlan, index: number, scene: Partial<SceneData>): EditPlan {
	const scenes = plan.scenes.map((s, i) => (i === index ? { ...s, ...scene } : s));
	return { ...plan, scenes };
}

export function addClip(plan: EditPlan, sceneIndex: number, clip: ClipData): EditPlan {
	const scenes = plan.scenes.map((s, i) => {
		if (i !== sceneIndex) return s;
		return { ...s, clips: [...s.clips, clip] };
	});
	return { ...plan, scenes };
}

export function removeClip(plan: EditPlan, sceneIndex: number, clipIndex: number): EditPlan {
	const scenes = plan.scenes.map((s, i) => {
		if (i !== sceneIndex) return s;
		return { ...s, clips: s.clips.filter((_, j) => j !== clipIndex) };
	});
	return { ...plan, scenes };
}

export function updateClip(plan: EditPlan, sceneIndex: number, clipIndex: number, clip: Partial<ClipData>): EditPlan {
	const scenes = plan.scenes.map((s, i) => {
		if (i !== sceneIndex) return s;
		const clips = s.clips.map((c, j) => (j === clipIndex ? { ...c, ...clip } : c));
		return { ...s, clips };
	});
	return { ...plan, scenes };
}

export function addEffect(plan: EditPlan, sceneIndex: number, clipIndex: number, effect: EffectEntry): EditPlan {
	const scenes = plan.scenes.map((s, i) => {
		if (i !== sceneIndex) return s;
		const clips = s.clips.map((c, j) => {
			if (j !== clipIndex) return c;
			return { ...c, effects: [...c.effects, effect] };
		});
		return { ...s, clips };
	});
	return { ...plan, scenes };
}

export function removeEffect(plan: EditPlan, sceneIndex: number, clipIndex: number, effectIndex: number): EditPlan {
	const scenes = plan.scenes.map((s, i) => {
		if (i !== sceneIndex) return s;
		const clips = s.clips.map((c, j) => {
			if (j !== clipIndex) return c;
			return { ...c, effects: c.effects.filter((_, k) => k !== effectIndex) };
		});
		return { ...s, clips };
	});
	return { ...plan, scenes };
}

export function setTransition(plan: EditPlan, sceneIndex: number, transition: TransitionData | null): EditPlan {
	const scenes = plan.scenes.map((s, i) => (i === sceneIndex ? { ...s, transition } : s));
	return { ...plan, scenes };
}

export function resetPlan(): EditPlan {
	return createDefaultPlan();
}

export function updatePlanSettings(plan: EditPlan, settings: Partial<Pick<EditPlan, 'output_size' | 'fps' | 'resize_mode' | 'audio_path'>>): EditPlan {
	return { ...plan, ...settings };
}
