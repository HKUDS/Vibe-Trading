import ExtensionAPI from '../../core/ExtensionAPI.js';
import GlobalModel from '../../model/Global.js';
import ComponentView from '../../view/Component.js';
import { ThumbnailModel } from './ThumbnailModel.js';
import { ThumbnailBridgeRendered } from './ThumbnailBridgeImpl.js';
export declare class ThumbnailView extends ComponentView {
    static type: "thumbnail";
    type: "thumbnail";
    private _api;
    private _model;
    private _bgRect;
    private _windowRect;
    private _contentRect;
    private _targetGroup;
    private _transThisToTarget;
    private _roamController;
    private _coordSys;
    private _bridgeRendered;
    private _renderVersion;
    render(thumbnailModel: ThumbnailModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    /**
     * Can be called asynchronously directly.
     * This method should be idempotent.
     */
    renderContent(bridgeRendered: ThumbnailBridgeRendered): void;
    private _dealRenderContent;
    /**
     * Can be called from action handler directly.
     * This method should be idempotent.
     */
    updateWindow(param: Pick<ThumbnailBridgeRendered, 'targetTrans' | 'renderVersion'>): void;
    private _dealUpdateWindow;
    private _resetRoamController;
    private _onPan;
    private _onZoom;
    /**
     * This method is also responsible for check enable in asynchronous situation,
     * e.g., in event listeners that is supposed to be outdated but not be removed.
     */
    private _isEnabled;
    private _clear;
    remove(): void;
    dispose(): void;
}
