using UnrealBuildTool;

public class WebSlingerEditorTarget : TargetRules
{
	public WebSlingerEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("WebSlinger");
	}
}
