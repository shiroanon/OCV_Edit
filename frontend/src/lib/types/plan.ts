export interface EffectParams {
	start_zoom?: number;
	end_zoom?: number;
	start_shift?: number;
	end_shift?: number;
	angle?: number;
	start_blur?: number;
	end_blur?: number;
	center?: [number, number];
	start_params?: Record<string, number>;
	end_params?: Record<string, number>;
	inner_color?: number[];
	outer_color?: number[];
	inner_radius?: number;
	outer_radius?: number;
	intensity?: number;
	pulse_speed?: number;
	pulse_amplitude?: number;
	text?: string;
	font_path?: string;
	font_size?: number;
	position?: string;
	color?: number[];
	opacity?: number;
	easing?: string;
	[key: string]: unknown;
}

export interface EffectEntry {
	type: string;
	start_time: number;
	duration: number;
	params: EffectParams;
}

export interface TransitionData {
	type: string;
	duration: number;
	params: Record<string, unknown>;
}

export interface ClipData {
	filepath: string;
	start_time: number;
	duration: number;
	speed: number;
	is_grid?: boolean;
	trans_dur?: number;
	effects: EffectEntry[];
	panels?: PanelData[];
}

export interface PanelData {
	file?: string;
	start_time?: number;
	speed?: number;
	flip?: string | null;
	ref_panel_idx?: number;
	effects: EffectEntry[];
}

export interface SceneData {
	start_beat_idx?: number;
	end_beat_idx?: number;
	t_start?: number;
	t_end?: number;
	out_dur: number;
	alignment_mode?: string;
	video_file: string;
	is_grid?: boolean;
	clips: ClipData[];
	transition: TransitionData | null;
}

export interface EditPlan {
	output_size: [number, number];
	fps: number;
	resize_mode: string;
	audio_path?: string;
	audio_total_dur?: number;
	global_effects: EffectEntry[];
	scenes: SceneData[];
}

export interface PlanMetadata {
	duration: number;
	fps: number;
	output_size: number[];
	scene_count: number;
	clip_count: number;
	effect_count: number;
	has_audio: boolean;
}

export interface FileEntry {
	name: string;
	path: string;
	size: number;
}

export interface PlanInfo {
	name: string;
	path: string;
	modified: number;
}

export interface ValidationResult {
	valid: boolean;
	errors: string[];
}

export interface ConfigResponse {
	effects: { type: string; params: Record<string, unknown> }[];
	transitions: { type: string; params: Record<string, unknown> }[];
}

export interface FrameRequest {
	plan: EditPlan;
	time: number;
	scale: number;
}

export interface SegmentRequest {
	plan: EditPlan;
	start_time: number;
	duration: number;
}

export interface SvelteFlowNodeData {
	label: string;
	planIndex?: number;
	[key: string]: unknown;
}

export interface VideoClipNodeData extends SvelteFlowNodeData {
	filepath: string;
	startTime: number;
	duration: number;
	speed: number;
	effects: EffectEntry[];
}

export interface TransitionNodeData extends SvelteFlowNodeData {
	transitionType: string;
	duration: number;
	params: Record<string, unknown>;
	direction?: string;
	mode?: string;
}

export interface EffectNodeData extends SvelteFlowNodeData {
	effectType: string;
	params: EffectParams;
}

export type TransitionType =
	| 'slide'
	| 'zoom'
	| 'grid_wipe'
	| 'flash'
	| 'radial_wipe'
	| 'zoom_in';
