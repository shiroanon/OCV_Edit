<script lang="ts">
	import Toolbar from '$lib/components/Toolbar.svelte';
	import NodeEditor from '$lib/components/NodeEditor.svelte';
	import PreviewPanel from '$lib/components/PreviewPanel.svelte';
	import PropertiesPanel from '$lib/components/PropertiesPanel.svelte';
</script>

<div class="app-layout">
	<Toolbar />
	<div class="main-area">
		<div class="editor-pane">
			<NodeEditor />
		</div>
		<div class="side-pane">
			<div class="preview-section">
				<PreviewPanel />
			</div>
			<PropertiesPanel />
		</div>
	</div>
</div>

<style>
	:global(body) {
		margin: 0;
		padding: 0;
		background: #0d0d1a;
		color: #e0e0e0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		overflow: hidden;
	}
	:global(*) {
		box-sizing: border-box;
	}
	.app-layout {
		display: flex;
		flex-direction: column;
		height: 100vh;
		width: 100vw;
	}
	.main-area {
		display: flex;
		flex: 1;
		overflow: hidden;
	}
	.editor-pane {
		flex: 1;
		min-width: 0;
	}
	.side-pane {
		display: flex;
		flex-direction: column;
		width: 480px;
		flex-shrink: 0;
		border-left: 1px solid #222;
	}
	.preview-section {
		height: 300px;
		flex-shrink: 0;
	}
</style>
