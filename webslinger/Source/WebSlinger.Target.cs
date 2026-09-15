using UnrealBuildTool;

public class WebSlingerTarget : TargetRules
{
	public WebSlingerTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("WebSlinger");
	}
}
