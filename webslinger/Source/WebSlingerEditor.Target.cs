using UnrealBuildTool;

public class WebSlingerEditorTarget : TargetRules
{
	public WebSlingerEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_5;
		ExtraModuleNames.Add("WebSlinger");
	}
}
