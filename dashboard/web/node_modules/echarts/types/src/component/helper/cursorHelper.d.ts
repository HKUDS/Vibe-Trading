import { ElementEvent } from 'zrender/lib/Element.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import type Component from '../../model/Component.js';
/**
 * Used on roam/brush triggering determination.
 * This is to avoid that: mouse clicking on an elements that is over geo or graph,
 * but roam is triggered unexpectedly.
 */
export declare function onIrrelevantElement(e: ElementEvent, api: ExtensionAPI, targetComponent: Component): boolean;
