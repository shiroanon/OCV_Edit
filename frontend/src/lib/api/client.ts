import { browser } from '$app/environment';
import type {
	ConfigResponse,
	EditPlan,
	FileEntry,
	PlanInfo,
	PlanMetadata,
	SegmentRequest,
	ValidationResult
} from '$lib/types/plan';

const BASE = 'http://localhost:8000';

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		...opts,
		headers: { 'Content-Type': 'application/json', ...(opts.headers as Record<string, string>) }
	});
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`API ${res.status}: ${text}`);
	}
	return res.json();
}

export const api = {
	config: () => request<ConfigResponse>('/api/config'),

	videos: () => request<FileEntry[]>('/api/videos'),

	audio: () => request<FileEntry[]>('/api/audio'),

	plans: () => request<PlanInfo[]>('/api/plans'),

	savePlan: (name: string, plan: EditPlan) =>
		request<PlanInfo>('/api/plans', {
			method: 'POST',
			body: JSON.stringify({ name, plan })
		}),

	loadPlan: (name: string) => request<EditPlan>(`/api/plans/${encodeURIComponent(name)}`),

	deletePlan: (name: string) =>
		request<{ deleted: string }>(`/api/plans/${encodeURIComponent(name)}`, { method: 'DELETE' }),

	planMetadata: (plan: EditPlan) =>
		request<PlanMetadata>('/api/plan/metadata', {
			method: 'POST',
			body: JSON.stringify({ plan })
		}),

	validatePlan: (plan: EditPlan) =>
		request<ValidationResult>('/api/plan/validate', {
			method: 'POST',
			body: JSON.stringify({ plan })
		}),

	previewFrame: async (plan: EditPlan, time: number): Promise<Blob> => {
		const res = await fetch(`${BASE}/api/preview/frame`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ plan, time })
		});
		if (!res.ok) throw new Error(`Frame preview failed: ${res.status}`);
		return res.blob();
	},

	previewSegment: async (req: SegmentRequest): Promise<Blob> => {
		const res = await fetch(`${BASE}/api/preview/segment`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(req)
		});
		if (!res.ok) throw new Error(`Segment preview failed: ${res.status}`);
		return res.blob();
	},

	render: async (plan: EditPlan, outputPath = 'output.mp4'): Promise<Blob> => {
		const res = await fetch(`${BASE}/api/render`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ plan, output_path: outputPath })
		});
		if (!res.ok) throw new Error(`Render failed: ${res.status}`);
		return res.blob();
	},

	health: () => request<{ status: string; timestamp: number }>('/api/health'),

	thumbnail: async (filepath: string, time = 0): Promise<Blob> => {
		const res = await fetch(`${BASE}/api/preview/thumbnail`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ filepath, time })
		});
		if (!res.ok) throw new Error(`Thumbnail failed: ${res.status}`);
		return res.blob();
	},

	autoEdit: (params: Record<string, unknown>) =>
		request<EditPlan>('/api/autoedit/plan', {
			method: 'POST',
			body: JSON.stringify(params)
		}),

	videoMetadata: (filepath: string) =>
		request<{ filepath: string; fps: number; duration: number; width: number; height: number; frames: number }>('/api/video/metadata', {
			method: 'POST',
			body: JSON.stringify({ filepath, time: 0 })
		}),
};
