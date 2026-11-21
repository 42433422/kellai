import type { Node } from '@xyflow/react';
import type { FlowDefinition, FlowNode } from '../types';

export type DraftNode = Node<{ label: string; draft: FlowNode }>;

export function toDraftNodes(nodes: FlowDefinition['nodes']): DraftNode[] {
  return nodes.map((node) => ({
    id: node.id,
    type: 'default',
    position: { ...node.position },
    data: { label: node.label, draft: structuredClone(node) },
  }));
}

/** Canvas styling never replaces the business node type or its configuration. */
export function fromDraftNodes(nodes: DraftNode[]): FlowDefinition['nodes'] {
  return nodes.map((node) => ({
    ...structuredClone(node.data.draft),
    id: node.id,
    label: node.data.label,
    position: { ...node.position },
  }));
}
